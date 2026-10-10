"""Run with: python -m streamlit run app.py"""
from __future__ import annotations
import copy
import json
import os
from statistics import pstdev
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from model import METRICS, CFB_METRICS, ensure_cfb_defaults, snapshot_season, project, quotes_for, run, validate
from data_pipeline import build_snapshot, request_bytes
from cfb_metrics import apply_cfb_inputs, attach_fei, preserve_cfb_overrides
from calibration import archive, attach_results, candidate, signature

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Football Model Lab', page_icon='🏈', layout='wide')
# Let Streamlit theme every foreground and background together. Fixed pale
# backgrounds become unreadable when the browser selects Streamlit's dark theme.
st.markdown('''<style>
 [data-testid="stMetric"]{border:1px solid var(--border-color,#80808040);border-radius:10px;padding:15px}
 .block-container{padding-top:2rem}button{border-radius:7px!important}
 </style>''',unsafe_allow_html=True)


def reset_widgets():
    for key in list(st.session_state):
        if key.startswith(('weight_','scenario_','team_')) or key in ('selected_matchup','dataset_json_editor'):del st.session_state[key]


def use_dataset(next_data):
    validate(next_data)
    ensure_cfb_defaults(next_data)
    st.session_state.data=copy.deepcopy(next_data)
    st.session_state.baseline=copy.deepcopy(next_data)
    reset_widgets()


def secret(name):
    try:return st.secrets.get(name,os.getenv(name,''))
    except Exception:return os.getenv(name,'')


if 'data' not in st.session_state:
    use_dataset(json.loads((ROOT/'snapshot.json').read_text()))
data=st.session_state.data

with st.sidebar:
    st.title('Football Model Lab')
    st.caption('NFL + CFB · Academic research')
    st.subheader('Model controls')
    if st.button('Reset model parameters',use_container_width=True,key='reset_parameters'):
        data['parameters']=copy.deepcopy(st.session_state.baseline['parameters']);reset_widgets();st.rerun()
    p=data['parameters']
    for key,label,lo,hi,step in [('by','Yards per play weight',0.,12.,.1),('bs','Success rate weight',0.,1.5,.01),('shrink','Efficiency shrinkage',0.,1.,.01),('turnover_retention','Turnover retention',0.,1.,.01),('turnover_point_value','Turnover point value',0.,8.,.1)]:
        # Expand the widget range to preserve imported coefficients.
        value=float(p[key]);p[key]=st.slider(label,min(lo,value),max(hi,value),value,step=step,key='weight_'+key)
    selected_league=st.selectbox('League assumptions',['NFL','CFB'])
    lp=p[selected_league]
    with st.expander('Scoring, venue and uncertainty',expanded=True):
        for key,label,minimum in [('q','Baseline points per team',1.),('bx','Explosiveness weight',None),('h','Home-field margin',0.),('sigma_spread','Spread residual sigma',.1),('sigma_total','Total residual sigma',.1)]:
            kwargs=dict(value=float(lp[key]),step=.1,key='weight_'+selected_league+'_'+key)
            if minimum is not None:kwargs['min_value']=minimum
            lp[key]=st.number_input(label,**kwargs)
    with st.expander('Reference metrics'):
        for key,label,minimum in [('n','Reference plays per team',1.),('y','Reference yards per play',0.),('s','Reference success %',0.),('x','Reference explosiveness',0.)]:
            lp[key]=st.number_input(label,min_value=minimum,value=float(lp[key]),step=.1,key='weight_'+selected_league+'_'+key)
    if selected_league == 'CFB':
        with st.expander('FEI and roster weights',expanded=True):
            lp['fei_weight']=st.slider('FEI forecast blend',0.,1.,float(lp['fei_weight']),step=.05,key='weight_CFB_fei_weight',help='25% combines 25% of the FEI possession forecast with 75% of the original efficiency forecast when both teams have valid FEI inputs.')
            for key,label,minimum,step in [('fei_drives','Reference possessions per team',.1,.5),('starter_weight','Points per extra returning starter',0.,.05),('starters_reference','Returning starters reference per unit',0.,.5),('portal_weight','Portal points per normalized rating',0.,.1),('portal_scale','Portal native rating units per point scale',.1,.5),('roster_half_life','Roster weight half-life in games',.1,.5)]:
                args=dict(min_value=minimum,value=float(lp[key]),step=step,key='weight_CFB_'+key)
                if key=='starters_reference': args['max_value']=11.
                lp[key]=st.number_input(label,**args)
            st.caption('Roster weight = 2^(−games played / half-life). Portal ratings compare incoming minus outgoing talent on the same provider scale. Weights need historical calibration.')
    with st.expander('Head-to-head history'):
        for key,label in [('h2h_margin_weight','History weight on margin'),('h2h_total_weight','History weight on total')]:
            lp[key]=st.slider(label,0.,1.,float(lp[key]),step=.05,key='weight_'+selected_league+'_'+key)
        for key,label in [('h2h_half_life_years','History half-life in years'),('h2h_prior_games','History prior sample size'),('h2h_difference_cap','Maximum historical discrepancy (points)')]:
            lp[key]=st.number_input(label,min_value=.1,value=float(lp[key]),step=.5,key='weight_'+selected_league+'_'+key)
        st.caption('Only completed meetings before the selected game count. Older games and small samples carry less weight.')
    with st.expander('Look-ahead and previous-game context',expanded=True):
        for key,label in [('lookahead_margin_points','Look-ahead margin effect per team'),('big_win_margin_points','After a major win: margin effect per team'),('road_loss_home_margin_points','Road loss then home: margin boost'),('lookahead_total_points','Look-ahead total effect per team'),('big_win_total_points','After a major win: total effect per team')]:
            lp[key]=st.number_input(label,value=float(lp[key]),step=.25,key='weight_'+selected_league+'_'+key)
        lp['context_window_days']=st.number_input('Maximum days between context games',min_value=1.,max_value=30.,value=float(lp['context_window_days']),step=1.,key='weight_'+selected_league+'_context_window_days')
        lp['major_opponent_points']=st.number_input('Major opponent: strength above average (points)',min_value=0.,value=float(lp['major_opponent_points']),step=.5,key='weight_'+selected_league+'_major_opponent_points')
        lp['context_cap_points']=st.number_input('Maximum combined context effect (points)',min_value=.01,value=float(lp['context_cap_points']),step=.25,key='weight_'+selected_league+'_context_cap_points')
        st.caption('Negative margin effects penalize the flagged team; positive effects favor it. Road loss then home starts at +0.5 margin points. Other effects start at zero. These are scenario assumptions; validate their effects on later games.')
    with st.expander('Margin and total calibration'):
        for key,label,minimum in [('margin_scale','Team-strength margin scale',.01),('margin_intercept','Margin intercept',None),('total_scale','Efficiency total scale',.01),('total_intercept','Total intercept',None)]:
            args=dict(value=float(lp[key]),step=.05,key='weight_'+selected_league+'_'+key)
            if minimum is not None:args['min_value']=minimum
            lp[key]=st.number_input(label,**args)
        st.caption('Keep scales at 1 and intercepts at 0 until later-game validation supports a correction. Larger margin scale amplifies team-strength differences; home field, injuries and schedule-context points retain their units.')
    st.caption('All coefficients and residual sigmas start as uncalibrated priors. Changing them tests assumptions.')

st.caption('RESEARCH WORKSPACE / SLATE EXPLORER')
st.title('Explore the slate.')
st.write('Rank the model estimates, inspect every game, and change the assumptions.')
mode=data.get('mode','snapshot')
st.info(('Frozen 11-game snapshot. Use Data & setup to load a full slate.' if mode=='snapshot' else 'Imported data. Verify timestamps, definitions, and coverage before interpreting the rankings.')+' Conditional EV has not been validated.')
st.caption('As of '+str(data.get('as_of',data.get('snapshot_date','unspecified')))+' · '+data.get('window',''))
for warning in data.get('warnings',[]):st.warning(warning)

tabs=st.tabs(['Slate explorer','Data & setup','Method & validation','Calibration diagnostics'])
results=run(data)

with tabs[0]:
    counts=st.columns(4)
    counts[0].metric('Games loaded',len(results));counts[1].metric('With projections',sum('away' in r for r in results));counts[2].metric('With usable odds',sum(bool(r['markets']) for r in results));counts[3].metric('Model version','Prototype 04')
    f=st.columns([1,1,1,2])
    league=f[0].selectbox('League',['All','NFL','CFB'])
    market=f[1].selectbox('Market',['All','Spreads','Totals'])
    side_type=f[2].selectbox('Spread side',['All','Favorites','Underdogs'],disabled=market=='Totals')
    search=f[3].text_input('Search team or matchup',placeholder='Buffalo, UCLA, Houston…')
    min_ev=st.slider('Minimum conditional EV %',0.,100.,0.,step=1.)/100
    kind={'All':None,'Spreads':'spread','Totals':'total'}[market]
    def best(r):
        def eligible(q):
            if q['conditional_ev']<=min_ev or (kind is not None and q['kind']!=kind):return False
            if side_type!='All' and market!='Totals':return q['kind']=='spread' and (q['line']<0 if side_type=='Favorites' else q['line']>0)
            return True
        return max((q for q in r['markets'] if eligible(q)),key=lambda q:q['conditional_ev'],default=None)
    def names(g):return data['teams'].get(g['away'],{}).get('name',g['away'])+' @ '+data['teams'].get(g['home'],{}).get('name',g['home'])
    visible=[r for r in results if (league=='All' or r['league']==league) and (not search or search.lower() in (names(r['game'])+' '+r['game']['away']+' '+r['game']['home']).lower())]
    st.subheader('Largest model discrepancies')
    st.caption('Top three per league by conditional EV; one quoted market per game.')
    for lg in (['NFL','CFB'] if league=='All' else [league]):
        ranked=sorted([r for r in visible if r['league']==lg and best(r)],key=lambda r:best(r)['conditional_ev'],reverse=True)[:3]
        st.markdown('**'+lg+'**')
        if not ranked:st.caption('No games with usable odds match this filter.')
        for col,r in zip(st.columns(3),ranked):
            q=best(r)
            with col:
                with st.container(border=True):
                    st.markdown('**'+names(r['game'])+'**')
                    st.metric('Projected score · Away – Home',f"{r['away']['score']:.1f} – {r['home']['score']:.1f}")
                    st.write(f"{q['label']} · {q['odds']:+g} · {q['book']}")
                    st.caption(f"{q['edge']:+.2f} points discrepancy · conditional EV {100*q['conditional_ev']:+.1f}%")
    st.subheader('Every loaded game')
    table=[]
    for r in visible:
        g=r['game'];q=best(r);row={'Matchup':names(g),'League':r['league'],'Status':r['status']}
        if 'away' in r:row.update({'Away score':r['away']['score'],'Home score':r['home']['score'],'Reference away spread':g.get('line_away'),'Model away spread':r['fair_line_away'],'Away spread difference':r['spread_edge_away'],'Reference total':g.get('total'),'Model total':r['fair_total'],'Over difference':r['total_edge_over']})
        row.update({'Best quoted market':q['label'] if q else None,'Book':q['book'] if q else None,'Conditional EV %':100*q['conditional_ev'] if q else None})
        extras=r.get('cfb_extensions')
        if extras:
            row.update({'FEI used':extras['fei_active'] and extras['fei_weight']>0,'Portal used':extras['portal_active'] and extras['parameters']['portal_weight']>0,'Away roster decay':extras['roster_decay']['away'],'Home roster decay':extras['roster_decay']['home']})
        if r.get('head_to_head'):row['Prior meetings']=r['head_to_head']['count']
        context=r.get('schedule_context')
        if context:
            row.update({'Away look-ahead':context['away']['lookahead'],'Home look-ahead':context['home']['lookahead'],'Away after major win':context['away']['big_win'],'Home after major win':context['home']['big_win'],'Home after road loss':context['home']['road_loss_return_home'],'Schedule margin effect':context['margin_adjustment'],'Schedule total effect':context['total_adjustment']})
        table.append(row)
    df=pd.DataFrame(table)
    if not df.empty:
        if 'Conditional EV %' in df:df=df.sort_values('Conditional EV %',ascending=False,na_position='last')
        st.dataframe(df,width='stretch',hide_index=True,height=min(650,38*len(df)+40))
        st.download_button('Download displayed projections',df.to_csv(index=False),file_name='projections.csv',mime='text/csv')
    else:st.caption('No games match your filters.')
    st.caption('Reference lines may be multi-book medians. Conditional EV always uses the individual quoted line and price.')
    if visible:
        game_ids=[results.index(r) for r in visible]
        index=st.selectbox('Inspect a matchup',game_ids,format_func=lambda i:names(results[i]['game']),key='selected_matchup')
        r=results[index];g=data['games'][index]
        with st.expander('Projection breakdown',expanded=True):
            if 'away' in r:
                breakdown=pd.DataFrame({g['away']:r['away']['score_parts'],g['home']:r['home']['score_parts']})
                st.dataframe(breakdown,width='stretch')
                st.write('Matched efficiency inputs')
                st.dataframe(pd.DataFrame({g['away']:r['away']['matched'],g['home']:r['home']['matched']}),width='stretch')
                st.write(f"Pace factor = {r['pace']:.6f}. Fair away spread = {r['fair_line_away']:+.6f}. Fair total = {r['fair_total']:.6f}.")
                for side in ('away','home'):
                    m=r[side]['matched'];lg=data['parameters'][r['league']]
                    st.code(f"{g[side]}: B = {lg['q']} + {p['shrink']} × [{p['by']}×({m['y']:.4f}−{lg['y']}) + {p['bs']}×({m['s']:.4f}−{lg['s']}) + {lg['bx']}×({m['x']:.4f}−{lg['x']})] = {r[side]['base']:.6f}\nScore = "+' '.join(f'{v:+.6f}' for v in r[side]['score_parts'].values())+f" = {r[side]['score']:.6f}")
                st.dataframe(pd.DataFrame(r['markets']),width='stretch',hide_index=True)
                extras=r.get('cfb_extensions')
                if extras:
                    st.write('FEI and roster contribution')
                    st.write(f"FEI blend: {extras['fei_weight']:.0%}. Estimated possessions per team: {extras['expected_drives']:.2f}.")
                    if extras['fei_active']:
                        st.code('\n'.join(f"{g[side]}: FEI forecast = {r[side]['fei_score']:.6f}; blend correction = {r[side]['score_parts']['fei_blend']:+.6f}; returning starters = {r[side]['score_parts']['returning_starters']:+.6f}; portal = {r[side]['score_parts']['portal']:+.6f}" for side in ('away','home')))
                    for note in dict.fromkeys(extras['notes']): st.caption(note)
                history=r.get('head_to_head',{})
                st.write('Head-to-head history')
                if history.get('count'):
                    st.write(f"{history['count']} previous meetings; current away team won {history['wins_away']}. Age-weighted sample: {history['weighted_games']:.2f}; shrinkage: {history['shrinkage']:.3f}.")
                    st.write(f"History margin adjustment: {history['margin_adjustment']:+.3f}; total adjustment: {history['total_adjustment']:+.3f} points.")
                    st.dataframe(pd.DataFrame(history['rows']),width='stretch',hide_index=True)
                else:st.caption(history.get('status','No history loaded. Refresh the slate to load historical meetings.'))
                context=r['schedule_context'];context_rows=[]
                st.write('Look-ahead and previous-game context')
                for side in ('away','home'):
                    info=context[side];previous=info['previous'] or {};following=info['next'] or {}
                    context_rows.append({'Team':data['teams'][g[side]].get('name',g[side]),'Next opponent':following.get('opponent'),'Days to next game':following.get('days_until'),'Next opponent strength':following.get('opponent_strength'),'Previous opponent':previous.get('opponent'),'Previous venue':previous.get('venue'),'Previous margin':previous.get('margin'),'Days since previous game':previous.get('days_since'),'Look-ahead':info['lookahead'],'Major win':info['big_win'],'Road loss then home':info['road_loss_return_home']})
                    for signal,label in [('lookahead','Look-ahead'),('big_win','Major win'),('road_loss_return_home','Road loss then home')]:
                        flag='Unknown' if info[signal] is None else 'Yes' if info[signal] else 'No'
                        st.caption(f"{g[side]} · {label}: {flag} · {info['sources'][signal]} · {info['reasons'].get(signal,'Does not qualify')}")
                st.dataframe(pd.DataFrame(context_rows),width='stretch',hide_index=True)
                dm,dt=context['margin_adjustment'],context['total_adjustment']
                st.code('Margin terms: '+json.dumps(context['margin_terms'])+'\nTotal terms: '+json.dumps(context['total_terms'])+f"\nCapped margin effect = {dm:+.3f}; total effect = {dt:+.3f}\nAway score effect = ({dm:+.3f} + {dt:+.3f}) / 2 = {(dm+dt)/2:+.3f}\nHome score effect = ({dt:+.3f} − {dm:+.3f}) / 2 = {(dt-dm)/2:+.3f}")
                if g.get('context_notes'):st.caption('Context note: '+g['context_notes'])
            else:st.warning(r['status']+' '+', '.join(r.get('missing',[])))
            st.caption(g.get('notes',''))
            if g.get('modifiers_verified') is False:st.warning('Injury, weather and rest modifiers have not been verified for this pull. Defaults are zero.')
        with st.expander('Edit matchup assumptions'):
            with st.form('scenario_form_'+str(index)):
                cols=st.columns(3);values={}
                defaults={'line_away':0.,'total':45.,'odds_away':-110.,'odds_home':-110.,'odds_over':-110.,'odds_under':-110.,'injury_away':0.,'injury_home':0.,'rest_margin_home':0.,'weather_total':0.}
                labels={'line_away':'Away spread','total':'Total','odds_away':'Away odds','odds_home':'Home odds','odds_over':'Over odds','odds_under':'Under odds','injury_away':'Away injury points','injury_home':'Home injury points','rest_margin_home':'Rest margin to home','weather_total':'Weather total adjustment'}
                qs=quotes_for(g)
                for i,(key,fallback) in enumerate(defaults.items()):
                    value=g.get(key)
                    if value is None and key.startswith('odds_'):value=next((q['odds'] for q in qs if q['selection']==key[5:]),fallback)
                    value=float(fallback if value is None else value)
                    step=1. if key.startswith('odds_') else .5 if key in ('line_away','total') else .1
                    values[key]=cols[i%3].number_input(labels[key],value=value,step=step,key='scenario_'+str(index)+'_'+key)
                values['neutral']=st.checkbox('Neutral venue',value=g.get('neutral',False),key='scenario_'+str(index)+'_neutral')
                if st.form_submit_button('Apply scenario'):
                    modified={**g,**values}
                    quote_changed=any(values[k]!=(g.get(k) if g.get(k) is not None else next((q['odds'] for q in qs if q['selection']==k[5:]),defaults[k]) if k.startswith('odds_') else defaults[k]) for k in ('line_away','total','odds_away','odds_home','odds_over','odds_under'))
                    if quote_changed or not qs:
                        modified.pop('quotes',None);modified['book']='Manual scenario';modified.pop('odds_updated_at',None)
                    try:
                        project(data,modified)
                        data['games'][index]=modified;st.rerun()
                    except (ValueError,ArithmeticError) as exc:st.error(str(exc))
        with st.expander('Edit schedule context'):
            st.caption('Automatic uses loaded schedules and frozen opponent strength. On/Off creates a manual scenario, which is retained in your JSON export. Refresh the slate to load schedules for this feature.')
            with st.form('context_form_'+str(index)):
                context_values={};columns=st.columns(2);options=['Automatic','On','Off']
                for col,side in zip(columns,('away','home')):
                    context_values[side]={};col.markdown('**'+g[side]+'**')
                    fields=[('lookahead','Look-ahead flag'),('big_win','Previous major-win flag')]
                    if side=='home' and not g.get('neutral'):fields.append(('road_loss_return_home','Road loss then home flag'))
                    for signal,label in fields:
                        current=g.get('context_overrides',{}).get(side,{}).get(signal)
                        choice=col.selectbox(g[side]+' · '+label,options,index=0 if current is None else 1 if current else 2,key='scenario_context_'+str(index)+'_'+side+'_'+signal)
                        context_values[side][signal]=None if choice=='Automatic' else choice=='On'
                context_note=st.text_input('Context note (rivalry, important opponent, source)',value=g.get('context_notes',''),key='scenario_context_'+str(index)+'_note')
                if st.form_submit_button('Apply schedule context'):
                    modified={**g,'context_overrides':context_values,'context_notes':context_note}
                    try:
                        validate({**data,'games':[modified]});project(data,modified)
                        data['games'][index]=modified;st.rerun()
                    except ValueError as exc:st.error(str(exc))
        with st.expander('Edit team metrics'):
            available=[tid for tid in (g['away'],g['home']) if tid in data['teams']]
            if available:
                team_id=st.selectbox('Team',available,key='team_id')
                with st.form('team_form_'+team_id):
                    current=data['teams'][team_id];inputs={};cols=st.columns(4)
                    for i,key in enumerate(METRICS):inputs[key]=cols[i%4].number_input(key,value=float(current.get(key) or 0),step=.1,key='team_'+team_id+'_'+key)
                    st.caption('y/dy: offense/allowed YPP; s/ds: success %; x/dx: explosive metric; p: plays per game; t: net turnovers per game. Zero fields above require your actual input before applying.')
                    if st.form_submit_button('Apply team statistics'):
                        data['teams'][team_id].update(inputs);st.rerun()
        if r['league']=='CFB':
            with st.expander('Edit FEI and roster inputs'):
                available=[tid for tid in (g['away'],g['home']) if tid in data['teams']]
                if available:
                    tid=st.selectbox('CFB team',available,format_func=lambda tid:data['teams'][tid].get('name',tid),key='team_cfb_id')
                    current=data['teams'][tid]
                    with st.form('cfb_inputs_'+tid):
                        columns=st.columns(2); inputs={}
                        labels={'ofei':'Offensive FEI (OFEI)','dfei':'Defensive FEI (DFEI)','returning_starters_off':'Returning offensive starters (0–11)','returning_starters_def':'Returning defensive starters (0–11)','portal_net_rating':'Net portal rating (sum in minus out)','roster_games_played':'Games played for roster decay'}
                        for i,key in enumerate(CFB_METRICS):
                            value=current.get(key)
                            if key=='roster_games_played' and value is None: value=current.get('sample_games')
                            args=dict(value=value,key='team_cfb_'+tid+'_'+key)
                            if key in ('returning_starters_off','returning_starters_def','roster_games_played'):
                                args.update(min_value=0,step=1,value=int(value) if value is not None else None)
                                if key.startswith('returning'): args['max_value']=11
                            else: args.update(step=.01,value=float(value) if value is not None else None)
                            inputs[key]=columns[i%2].number_input(labels[key],**args)
                        year=snapshot_season(data) or datetime.now().year
                        fei_season=columns[0].number_input('FEI season',value=int(current.get('fei_season') or year),step=1,key='team_cfb_'+tid+'_fei_season')
                        through=current.get('fei_through_week')
                        fei_week=columns[1].number_input('FEI through week',min_value=0,value=int(through) if through is not None else None,step=1,key='team_cfb_'+tid+'_fei_week')
                        roster_season=columns[0].number_input('Roster season',value=int(current.get('roster_season') or year),step=1,key='team_cfb_'+tid+'_roster_season')
                        st.caption('Blank means unknown. Positive DFEI is a stronger defense. Use the numeric FEI rating, not its rank. Portal sums must use one consistent provider rating scale.')
                        if st.form_submit_button('Apply FEI and roster inputs'):
                            record={k:v for k,v in inputs.items() if v!=current.get(k)}
                            if any(k in record for k in ('ofei','dfei')) or fei_season!=current.get('fei_season') or fei_week!=current.get('fei_through_week'):
                                record.update(fei_season=fei_season,fei_through_week=fei_week,fei_source='Manual FEI inputs')
                            if any(k in record for k in ('returning_starters_off','returning_starters_def','portal_net_rating','roster_games_played')) or roster_season!=current.get('roster_season'):
                                record.update(roster_season=roster_season,roster_source='Manual roster inputs')
                            try:
                                updated,_,_=apply_cfb_inputs(data,{tid:record});use_dataset(updated);st.rerun()
                            except ValueError as exc: st.error(str(exc))

with tabs[1]:
    st.subheader('Load a full slate')
    st.write('Select a date window, supply provider keys, then refresh explicitly. Model-control changes reuse the loaded data.')
    today=datetime.now(ZoneInfo('America/New_York')).date()
    with st.form('data_refresh'):
        c=st.columns(3)
        season=c[0].number_input('Season',min_value=1999,max_value=2100,value=today.year,step=1)
        start=c[1].date_input('First date',today)
        end=c[2].date_input('Last date',today+timedelta(days=7))
        leagues=st.multiselect('Leagues',['NFL','CFB'],default=['NFL','CFB'])
        c=st.columns(2)
        cfbd_key=c[0].text_input('CollegeFootballData API key',value=secret('CFBD_API_KEY'),type='password')
        odds_key=c[1].text_input('The Odds API key',value=secret('ODDS_API_KEY'),type='password')
        regions=st.selectbox('Book region',['us','us2','uk','eu','au'])
        refresh=st.form_submit_button('Refresh schedules, statistics and odds')
    if refresh:
        with st.spinner('Loading schedules and prior-week statistics…'):
            try:
                current_params=copy.deepcopy(data['parameters'])
                next_data=build_snapshot(int(season),start,end,leagues,cfbd_key,odds_key,regions)
                next_data['parameters']=current_params
                next_data=preserve_cfb_overrides(data,next_data)
                use_dataset(next_data);st.rerun()
            except Exception as exc:st.error('Refresh did not replace your dataset. '+str(exc))
    st.caption('NFL statistics use eligible prior-week plays. CFB uses prior-week advanced stats plus box scores. Feed access, quota and publication timing determine coverage. First-week teams need preseason priors or manually supplied statistics.')
    st.caption('Refresh also loads current-season schedules for next opponents and previous results. Missing schedules or opponent strength remain unknown. The frozen example needs a schedule refresh for automatic context flags.')
    st.subheader('CFB FEI and roster inputs')
    st.write('FEI loads from BCF Toys during a CFB refresh. Portal ratings load through your CFBD key. Returning starters need verified offensive and defensive counts. Manual overrides are retained in exported JSON and reapplied within the same season on a slate refresh.')
    cfb_teams={tid:t for tid,t in data['teams'].items() if t.get('league')=='CFB'}
    if cfb_teams:
        st.dataframe(pd.DataFrame([{'Team':t.get('name',tid),'OFEI':t.get('ofei'),'DFEI':t.get('dfei'),'FEI through week':t.get('fei_through_week'),'Returning offense':t.get('returning_starters_off'),'Returning defense':t.get('returning_starters_def'),'Net portal rating':t.get('portal_net_rating'),'Games played':t.get('roster_games_played') if t.get('roster_games_played') is not None else t.get('sample_games')} for tid,t in cfb_teams.items()]),hide_index=True,width='stretch')
        if st.button('Load latest FEI for loaded CFB teams'):
            try:
                updated=copy.deepcopy(data); year=snapshot_season(data) or int(season)
                cutoffs=[g['feature_through_week'] for g in data['games'] if g.get('league')=='CFB' and g.get('feature_through_week') is not None]
                attach_fei(updated['teams'],request_bytes(f'https://bcftoys.com/{year}-fei',ttl=3600).decode('utf-8'),year,min(cutoffs) if cutoffs else None)
                for record in updated.get('cfb_overrides',{}).values():
                    for key in ('ofei','dfei','fei_season','fei_through_week','fei_source'): record.pop(key,None)
                use_dataset(updated);st.rerun()
            except (RuntimeError,ValueError,UnicodeError) as exc: st.error(str(exc))
        template={'teams':{t.get('name',tid):{**{k:None for k in CFB_METRICS},'fei_season':snapshot_season(data),'fei_through_week':None,'roster_season':snapshot_season(data)} for tid,t in cfb_teams.items()}}
        st.download_button('Download CFB input template',json.dumps(template,indent=2),file_name='cfb_inputs.json',mime='application/json')
        supplement=st.file_uploader('Import FEI and roster JSON',type=['json'],key='cfb_input_upload')
        if supplement and st.button('Merge CFB inputs'):
            try:
                uploaded=json.load(supplement);updated,matched,unmatched=apply_cfb_inputs(data,uploaded.get('teams',{}),ignore_nulls=True)
                if not matched: raise ValueError('No CFB input teams matched the loaded teams.')
                use_dataset(updated);st.rerun()
            except (ValueError,TypeError) as exc: st.error(str(exc))
        st.caption('Blank/null fields in this template preserve existing inputs. Use the team editor to clear a field. Manual FEI ratings keep their through-week until you refresh FEI explicitly. Export the full snapshot to keep edits between browser sessions.')
    st.subheader('Import or export a snapshot')
    upload=st.file_uploader('Import JSON',type=['json'])
    if upload and st.button('Load uploaded snapshot'):
        try:
            parsed=json.load(upload);use_dataset(parsed.get('snapshot',parsed));st.rerun()
        except (ValueError,KeyError,TypeError) as exc:st.error(str(exc))
    st.download_button('Export model inputs and settings',json.dumps(data,indent=2,allow_nan=False),file_name='football_model_snapshot.json',mime='application/json')
    st.caption('Keep the full JSON to restore inputs, weights, historical meetings and manual overrides in a later Streamlit session.')
    with st.expander('Edit the complete dataset JSON'):
        text=st.text_area('Teams, games, markets, parameters and sources',json.dumps(data,indent=2),height=350,key='dataset_json_editor')
        if st.button('Apply complete JSON'):
            try:use_dataset(json.loads(text));st.rerun()
            except (ValueError,KeyError,TypeError) as exc:st.error(str(exc))
    if st.button('Restore original 11-game snapshot'):
        use_dataset(json.loads((ROOT/'snapshot.json').read_text()));st.rerun()

with tabs[2]:
    st.subheader('Score equations')
    st.code('M = (offensive metric + opponent allowed metric) / 2\nF = (away plays + home plays) / (2 × reference plays)\nB = baseline + shrink × [bY×(Y−Yref) + bS×(S−Sref) + bX×(X−Xref)]\nT = turnover point value × retention × (away net TO − home net TO) / 4\nAway score = F×Baway + T − (home field+rest)/2 + injury away + weather/2\nHome score = F×Bhome − T + (home field+rest)/2 + injury home + weather/2\nFair away spread = home score − away score\nFair total = home score + away score\nConditional EV = net profit multiple × P(win) − P(loss)')
    st.write('Home field is zero at neutral venues. Extra travel is currently absorbed into home field. Turnover retention is a relative-rating proxy; it is not a separately estimated fumble recovery model.')
    st.subheader('CFB FEI, continuity and portal equations')
    st.code('C_i = original pace-adjusted efficiency forecast\nD = pace × reference possessions\nE_i = pace × baseline + D × (OFEI_i − DFEI_opponent)\nBlended efficiency = (1−wFEI) × C_i + wFEI × E_i\nd_i = 2^(−games_played_i / roster_half_life)\nReturning adjustment_i = bStarter × [d_i × (off_starters_i−reference) − d_opponent × (def_starters_opponent−reference)]\nNet portal rating_i = sum(incoming provider ratings) − sum(outgoing provider ratings)\nAway portal adjustment = bPortal × (d_away × net_away − d_home × net_home) / (2 × portal_scale)\nHome portal adjustment = −Away portal adjustment\nFinal score = blended efficiency + returning adjustment + portal adjustment + existing game modifiers')
    st.write('FEI is blended into the efficiency forecast; overall FEI and its ranks are not added again. The FEI baseline and possession conversion are modeling assumptions because the source rates non-garbage possessions. Positive DFEI lowers the opponent score. Portal is a coarse team-strength adjustment to margin and does not change the total.')
    st.write('Head-to-head uses up to five prior seasons from the schedule feeds. Past margins are converted to the current team perspective and approximately neutralized for home field. Age weights have a 2-year half-life; effective sample shrinkage is n/(n+8). Only 10% of a discrepancy capped at 10 points is applied by default. Old matchup results are a weak contextual prior because players, coaches, and team strength change.')
    st.subheader('Schedule context equations')
    st.code('L_i = next major game within the time window, with current opponent below the major threshold\nW_i = previous completed win over a major opponent within the time window\nR_i = previous completed road loss, followed by a non-neutral home game within the time window\nΔMargin = clip(bL×(L_away−L_home) + bW×(W_away−W_home) + bR×(R_away−R_home), −cap, cap)\nΔTotal = clip(tL×(L_away+L_home) + tW×(W_away+W_home), −cap, cap)\nAway score contribution = (ΔMargin+ΔTotal)/2\nHome score contribution = (ΔTotal−ΔMargin)/2')
    st.write('Major opponents use a frozen neutral-strength proxy: shrink × [bY×(y−dy)+bS×(s−ds)+bX×(x−dx)]/2. CFB blends that proxy with reference possessions × (OFEI+DFEI) when dated FEI is eligible. Default major thresholds are 4 points above average for NFL and 8 for CFB. Explicit schedule major_game tags or per-game manual flags support rivalry context. Unknown inputs produce no automatic adjustment; future results are never used.')
    st.write('The default time window is 10 days and the combined margin/total adjustments are each capped at 2 points. Look-ahead and major-win weights start at zero; set signed effects to test a letdown or confidence scenario. Returning home after a verified road loss gets a provisional +0.5 margin-point boost, separate from normal home field, with no automatic change to the total. These effects need historical validation and are not multiplied by the score-calibration slope.')
    st.write('Default CFB priors: 25% FEI blend, 12 reference possessions, 0.20 points per extra returning starter, 1 portal point per 5 native net-rating units, and a 4-game roster half-life. Missing FEI disables the game’s FEI blend; missing roster inputs skip their terms. These values require chronological validation and may overlap with FEI preseason priors or current-season efficiency.')
    st.write('Normal residuals use integer push bins and half-point lines. The distribution does not model football scoring clusters at 3 and 7. Uncertainty and probabilities need out-of-sample calibration.')
    st.subheader('The path to prediction quality')
    st.markdown('''1. Store immutable, timestamped features and odds before kickoff, plus eventual results.
2. Fit separate NFL and CFB models with opponent adjustment, regularization and sample-size shrinkage.
3. Validate on later weeks/seasons. Compare margin and total MAE/RMSE with a timestamp-matched market baseline.
4. Calibrate cover/over probabilities and the score distribution on held-out games. Evaluate Brier score, log loss and calibration plots.
5. Select weights and thresholds on training/validation data; report final test results once. Rank future games only after measuring uncertainty and stability.
''')
    st.write('This package supplies an editable prototype and data pipeline. It does not contain historically fitted coefficients, an automated injury feed, or proof of profitable returns.')
    st.json(data.get('sources',{}))

with tabs[3]:
    st.subheader('Favorite and underdog diagnostics')
    st.write('These summaries use the best quoted spread per game. They identify concentration and compressed forecasts; they do not establish which side will outperform.')
    for lg in ('NFL','CFB'):
        rows=[];model_margins=[];market_margins=[]
        for r in results:
            if r['league']!=lg or 'away' not in r:continue
            spreads=[q for q in r['markets'] if q['kind']=='spread']
            if not spreads:continue
            q=max(spreads,key=lambda q:q['conditional_ev'])
            reference=r['game'].get('line_away')
            if reference is not None:model_margins.append(r['margin_away']);market_margins.append(-reference)
            rows.append({'Matchup':r['game']['away']+' @ '+r['game']['home'],'Quoted selection':q['label'],'Side':'Favorite' if q['line']<0 else 'Underdog' if q['line']>0 else 'Pick’em','Conditional EV %':100*q['conditional_ev'],'Qualifies':q['conditional_ev']>min_ev})
        st.markdown('**'+lg+'**')
        if rows:
            qualifying=[row for row in rows if row['Qualifies']]
            st.write(f"Qualifying spread signals: {sum(row['Side']=='Favorite' for row in qualifying)} favorites, {sum(row['Side']=='Underdog' for row in qualifying)} underdogs, {sum(row['Side']=='Pick’em' for row in qualifying)} pick’em.")
            if len(model_margins)>1 and pstdev(market_margins)>0:
                ratio=pstdev(model_margins)/pstdev(market_margins)
                st.write(f"Margin standard deviation: model {pstdev(model_margins):.2f}, market {pstdev(market_margins):.2f}; ratio {ratio:.2f}.")
                if ratio<.85:st.warning('Model margins are compressed relative to this slate’s market. Check opponent strength, input quality and historical calibration before interpreting the underdog concentration.')
            st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
        else:st.caption('No usable spread quotes loaded.')
    st.subheader('Learn calibration from archived pregame forecasts')
    st.write('Archive forecasts before kickoff. After the games finish, load their results and import your archive here. The fitter requires at least 80 distinct completed games per league with the same model settings, uses older games for training and later games for validation, and applies only corrections that improve validation RMSE.')
    archived=archive(data,results)
    st.download_button('Archive current pregame forecasts',json.dumps(archived,indent=2),file_name='pregame_forecasts.json',mime='application/json',disabled=not archived['forecasts'])
    if not archived['forecasts']:st.caption('No future games with verified kickoff timestamps are loaded. Refresh schedules before archiving.')
    calibration_upload=st.file_uploader('Import calibration archive JSON',type=['json'],key='calibration_upload')
    calibration_league=st.selectbox('Calibration league',['NFL','CFB'])
    if calibration_upload:
        try:
            payload=json.load(calibration_upload); records=attach_results(payload['forecasts'],data)
            st.download_button('Download archive with available results',json.dumps({'format':'pregame-calibration-v1','forecasts':records},indent=2),file_name='forecasts_with_results.json',mime='application/json')
            if st.button('Fit and validate calibration'):
                report=candidate(records,calibration_league,signature(data))
                st.session_state['calibration_report']=report
                st.session_state['calibration_signature']=signature(data)
        except (ValueError,TypeError,KeyError) as exc:st.error(str(exc))
    report=st.session_state.get('calibration_report')
    if report and report['league']==calibration_league:
        st.json(report)
        improvements=[target for target in ('margin','total') if report['metrics'][target]['improves']]
        if improvements and st.session_state.get('calibration_signature')==signature(data):
            if st.button('Apply validated corrections'):
                for target in improvements:
                    for key,value in report['coefficients'][target].items():data['parameters'][calibration_league][target+'_'+key]=value
                reset_widgets();st.rerun()
        else:st.caption('No correction qualifies, or the model settings changed. Refit after reviewing the data.')
