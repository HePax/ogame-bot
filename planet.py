# -*- coding: utf-8 -*-
from config import options
import math


class Planet(object):
    def __init__(self, id, name, coords, url, in_construction_mode=False):
        self.id = id
        self.name = name
        self.url = url
        self.coords = coords
        self.mother = False
        self.galaxy, self.system, self.position = map(int, self.coords.split(":"))
        self.in_construction_mode = in_construction_mode
        self.mines = (
            'Metal Mine',
            'Crystal Mine',
            'Deuterium Synthesizer'
        )
        self.resources = {
            'metal': 0,
            'crystal': 0,
            'deuterium':0,
            'energy':0
        }

        self.buildings = {
            'Metal Mine': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': False
            },
            'Crystal Mine': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': False
            },
            'Deuterium Synthesizer': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': False
            },
            'Solar Plant': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': True
            },
            'Fusion Plant': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': True
            },
            'Solar Satellite': {
                'level': 0,
                'buildUrl':'',
                'can_build': False,
                'sufficient_energy': True
            },
        }

        self.ships = {
            'lm': 0,
            'hm': 0,
            'cr': 0,
            'ow': 0,
            'pn': 0,
            'bb': 0,
            'ns': 0,
            'gs': 0,
            'lt': 0,
            'dt': 0,
            'cs': 0,
            'rc': 0,
            'ss': 0
        }

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.id == other.id
        
    def strtocheck(self, s):
        s=s.strip().lower()
        if s in ["done","ok","finished","completed","terminado","okay","-1"]:
            return -1
        else:
            try:
                return int(s)
            except ValueError:
                return 0
        return 0
    def checktostr(self, v):
        if v==-1:
            return 'done'
        else:
            return str(v)

    def get_upgrades(self):
        build_options = options['building']
        buildlist = [s for s in build_options['list'].split(',') if s.strip()]
        updated=False
        if build_options.has_key('checklist'):
            checklist=[self.strtocheck(s) for s in build_options['checklist'].split(',') if s.strip()]
        else:
            checklist=[]
        if len(checklist)>len(buildlist):
            checklist=[0]*len(buildlist)
            updated=True
        elif len(checklist)<len(buildlist):
            checklist+=[0]*(len(buildlist)-len(checklist))
            updated=True
        try:
            for i,st in enumerate(checklist):
                if st>=0:
                    name,lvl=[s.strip() for s in buildlist[i].strip().split(':')]
                    lvl=int(lvl)
                    if name in self.buildings:
                        if lvl>self.buildings[name]['level']:
                            if self.buildings[name]['link']:
                                return {'buildings':[name]}
                            else:
                                return {}
                        else:
                            checklist[i]=-1
                            updated=True
                    elif name in self.researches:
                        if lvl>self.researches[name]['level']:
                            print self.researches[name]['level']
                            if self.researches[name]['link']:
                                return  {'researches':[name]}
                            else:
                                return {}
                        else:
                            checklist[i]=-1
                            updated=True
                    elif name in self.buyable_fleets:
                        cant=max(0, lvl-st)
                        if cant==0:
                            checklist[i] = -1
                            updated=True
                        tobuild=min(cant, self.get_max_possible(self.buyable_fleets[name]))
                        if tobuild>0:
                            checklist[i]+=tobuild
                            if checklist[i]==lvl:
                                checklist[i] = -1
                            updated=True
                            return {'fleets' : {name:tobuild}}
        finally:
            if updated:
                options.change_item('building', 'checklist', ', '.join(map(self.checktostr, checklist)))
        return self.get_mine_to_upgrade_classic()

    def get_max_possible(self, cost):
        mx=-1
        for r,a in cost.iteritems():
            if r not in self.resources:
                return 0
            l=int(math.floor(self.resources[r]/a))
            if mx==-1:
                mx=l
            else:
                mx=min(mx, l)
        return max(mx,0)
        
    def get_mine_to_upgrade_classic(self):
        build_options = options['building']
        levels_diff = map(int, build_options['levels_diff'].split(','))
        max_fusion_lvl = int(build_options['max_fusion_plant_level'])

        b = self.buildings
        build_power_plant = self.resources['energy'] <= 0

        mine_levels = [0, 0, 0]

        for i, mine in enumerate(self.mines):
            mine_levels[i] = b[mine]['level']

        proposed_levels =[
            b['Metal Mine']['level'],
            b['Metal Mine']['level'] - levels_diff[0],
            b['Metal Mine']['level'] - levels_diff[0] - levels_diff[1]
        ]
        proposed_levels = [0 if l < 0 else l for l in proposed_levels]
        if proposed_levels == mine_levels or (mine_levels[1] >= proposed_levels[1] and mine_levels[2] >= proposed_levels[2]):
            proposed_levels[0] += 1

        num_suff_energy = 0
        for i in xrange(3):
            building = self.mines[i]
            if b[building]['sufficient_energy']:
                num_suff_energy += 1
            if b[building]['link'] and proposed_levels[i] > b[building]['level']:
                if b[building]['sufficient_energy']:
                    return building
                else:
                    build_power_plant = True

        if build_power_plant or num_suff_energy == 0:
            if b['Solar Plant']['link']:
                return u'Solar Plant'
            elif b.has_key('Fusion Plant') and b['Fusion Plant']['link'] and \
                    b['Fusion Plant']['level'] < max_fusion_lvl:
                return u'Fusion Plant'
            else:
                return None
        else:
            return None

    def is_moon(self):
        return False

    def has_ships(self):
        '''
        Return true if any ship is stationing on the planet
        '''
        return any(self.ships.values())

    def get_distance(self, planet):
        """
        Return distance to planet `planet`
        """
        try:
            g, s, p = map(int, planet.split(":"))
        except Exception:
            return 100000
        d = 0
        d += (abs(g - self.galaxy) * 100)
        d += (abs(s - self.system) * 10)
        d += (abs(p - self.position))

        return d

    def get_fleet_for_resources(self, r):
        total = sum([r.get('metal', 0), r.get('crystal', 0), r.get('deuterium', 0)])
        to_send = 0
        ships = {'dt': 0, 'lt': 0}
        for kind in ('dt', 'lt'):
            if self.ships[kind] > 0:
                for i in xrange(self.ships[kind]):
                    to_send += (25000 if kind == 'dt' else 5000)
                    ships[kind] += 1
                    if to_send > total:
                        return ships
        return ships

    def get_nearby_systems(self, radius):
        g, s, p = map(int, self.coords.split(":"))
        start_system = max(1, s-radius)
        end_system = min(499, s+radius)
        systems = []
        for system in xrange(start_system, end_system):
            systems.append("%s:%s" % (g, system))

        return systems

class Moon(Planet):

    def __init__(self, id, coords, url):
        super(Moon, self).__init__(id, 'Moon', coords, url)

    def get_mine_to_upgrade(self):
        return None, None

    def is_moon(self):
        return True

    def __str__(self):
        return '[%s] %s' % (self.coords, self.name)
