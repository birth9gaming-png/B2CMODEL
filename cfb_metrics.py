"""CFB possession ratings, preseason transfer aggregates and manual roster inputs."""
from __future__ import annotations
import copy
import math
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from model import CFB_METRICS, ensure_cfb_defaults, snapshot_season, validate

INPUT_FIELDS = CFB_METRICS + ('fei_season', 'fei_through_week', 'roster_season', 'fei_source', 'roster_source')


def normalized(name):
    return re.sub(r'[^a-z0-9]', '', str(name).lower())


class RatingTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.text=[]

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row=[]
        elif tag in ('td', 'th') and self.row is not None: self.cell=[]

    def handle_data(self, value):
        self.text.append(value)
        if self.cell is not None: self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split())); self.cell=None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row=None


def parse_fei(html, season):
    parser=RatingTable(); parser.feed(html)
    text=' '.join(parser.text)
    if not re.search(r'\b' + str(season) + r'\s+FEI\s+Ratings', text, re.I):
        raise ValueError('FEI page does not identify the requested season.')
    found=re.search(r'through\s+Week\s+(\d+)', text, re.I)
    if found is None:
        raise ValueError('FEI page has no through-week label; use a dated manual import.')
    week=int(found.group(1)); columns=None; ratings={}
    for row in parser.rows:
        if all(k in row for k in ('Team', 'OFEI', 'DFEI')):
            columns={k:row.index(k) for k in ('Team', 'OFEI', 'DFEI')}; continue
        if columns is None or len(row) <= max(columns.values()) or not row[0].isdigit(): continue
        try: off, defense = float(row[columns['OFEI']]), float(row[columns['DFEI']])
        except ValueError: continue
        if not all(math.isfinite(v) for v in (off, defense)): continue
        name=row[columns['Team']]
        if normalized(name) in ratings: raise ValueError('Duplicate team in FEI table.')
        ratings[normalized(name)]=dict(ofei=off,dfei=defense,fei_season=season,fei_through_week=week)
    if not ratings: raise ValueError('FEI table could not be parsed; ratings were not guessed.')
    return ratings, week


def attach_fei(teams, html, season, cutoff=None):
    ratings, week=parse_fei(html, season)
    if cutoff is not None and week > cutoff:
        raise ValueError(f'Latest FEI is through week {week}, after cutoff {cutoff}. Import an archived pregame rating instead.')
    matched=0
    for team in teams.values():
        if team.get('league') != 'CFB': continue
        values=ratings.get(normalized(team.get('name', '')))
        if values:
            team.update(values,fei_source=f'https://bcftoys.com/{season}-fei',fei_loaded_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            matched+=1
    if not matched: raise ValueError('No FEI team names matched the CFB teams in this snapshot.')
    return matched, week


def portal_ratings(rows, season, preseason_cutoff):
    """Sum provider ratings in minus out; only dated, confirmed immediate transfers."""
    totals={}; incomplete=set(); seen=set()
    def start(name):
        key=normalized(name)
        totals.setdefault(key, dict(portal_net_rating=0., portal_incoming=0, portal_outgoing=0))
        return key
    for row in rows:
        if row.get('season') != season: continue
        origin, destination=row.get('origin'),row.get('destination')
        if not origin or not destination or normalized(origin)==normalized(destination): continue
        if row.get('eligibility') == 'Withdrawn': continue
        keys=[normalized(origin),normalized(destination)]
        date=row.get('transferDate')
        try:
            transfer=datetime.fromisoformat(date.replace('Z','+00:00'))
            if transfer.tzinfo is None: transfer=transfer.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, AttributeError):
            incomplete.update(keys); continue
        if transfer >= preseason_cutoff: continue
        if row.get('eligibility') != 'Immediate':
            incomplete.update(keys); continue
        identity=(row.get('firstName'),row.get('lastName'),row.get('position'),normalized(origin),normalized(destination),date)
        if identity in seen: continue
        seen.add(identity)
        try: rating=float(row.get('rating'))
        except (ValueError, TypeError): incomplete.update(keys); continue
        if not math.isfinite(rating) or rating < 0:
            incomplete.update(keys); continue
        a,h=start(origin),start(destination)
        totals[a]['portal_net_rating']-=rating; totals[a]['portal_outgoing']+=1
        totals[h]['portal_net_rating']+=rating; totals[h]['portal_incoming']+=1
    for key in incomplete:
        totals.setdefault(key,dict(portal_incoming=0,portal_outgoing=0))['portal_net_rating']=None
    return totals


def attach_portal(teams, rows, season, preseason_cutoff):
    if not rows: raise ValueError('Portal feed returned no records; net ratings remain unknown.')
    totals=portal_ratings(rows,season,preseason_cutoff)
    incomplete=0
    for team in teams.values():
        if team.get('league') != 'CFB': continue
        values=totals.get(normalized(team.get('name','')),dict(portal_net_rating=0.,portal_incoming=0,portal_outgoing=0))
        team.update(values,roster_season=season,portal_source='CFBD /player/portal: confirmed immediate transfers, native rating sum in minus out',portal_cutoff=preseason_cutoff.isoformat())
        if values['portal_net_rating'] is None: incomplete+=1
    return incomplete


def apply_cfb_inputs(data, records, remember=True, ignore_nulls=False):
    """Join exact normalized names/IDs; bulk templates may leave nulls untouched."""
    result=copy.deepcopy(data); ensure_cfb_defaults(result)
    if not isinstance(records,dict): raise ValueError('CFB input file needs a teams object.')
    names={}
    for tid, team in result['teams'].items():
        if team.get('league') != 'CFB': continue
        for name in (tid,team.get('name',tid)):
            names.setdefault(normalized(name),set()).add(tid)
    unmatched=[]; updates=[]; targeted=set()
    for name,record in records.items():
        if not isinstance(record,dict): raise ValueError('Each team input must be an object.')
        matches=names.get(normalized(name),set())
        if len(matches)!=1: unmatched.append(name); continue
        tid=next(iter(matches))
        if tid in targeted: raise ValueError('More than one input record matches ' + tid)
        targeted.add(tid)
        values={k:v for k,v in record.items() if k in INPUT_FIELDS and (v is not None or not ignore_nulls)}
        # Forms can explicitly clear a metric. Blank bulk-template fields preserve it.
        result['teams'][tid].update(values)
        if remember:
            result.setdefault('cfb_overrides',{}).setdefault(result['teams'][tid].get('name',tid),{}).update(values)
        updates.append(tid)
    validate(result)
    if unmatched: result.setdefault('warnings',[]).append('CFB inputs not joined: ' + ', '.join(unmatched))
    return result, updates, unmatched


def preserve_cfb_overrides(previous, next_data):
    season=snapshot_season(next_data); accepted={}
    for name, record in previous.get('cfb_overrides',{}).items():
        values=copy.deepcopy(record)
        if values.get('roster_season') != season:
            values={k:v for k,v in values.items() if k.startswith('fei_') or k in ('ofei','dfei')}
        if values.get('fei_season') != season:
            values={k:v for k,v in values.items() if not k.startswith('fei_') and k not in ('ofei','dfei')}
        # Games played advances with the newly loaded statistics, unless edited again.
        values.pop('roster_games_played',None)
        if values: accepted[name]=values
    if accepted:
        result,_,_=apply_cfb_inputs(next_data,accepted)
        return result
    return next_data
