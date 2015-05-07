# -*- coding: utf-8 -*-
import socket
import random
from math import floor
from BeautifulSoup import BeautifulSoup
from logging.handlers import RotatingFileHandler
import time
from datetime import date
import logging
import mechanize
import os
import re
from random import randint
from datetime import datetime
from utils import *
from urllib import urlencode
from planet import Planet, Moon
from attack import Attack
from transport_manager import TransportManager
from config import options
from sim import Sim
socket.setdefaulttimeout(float(options['general']['timeout']))


class Bot(object):

    BASE_URL = 'http://labdcc.fceia.unr.edu.ar/~jgalat/'
    LOGIN_URL = 'http://labdcc.fceia.unr.edu.ar/~jgalat/'
    HEADERS = [('User-agent', 'Mozilla/5.0 (Windows NT 6.2; WOW64)\
     AppleWebKit/537.15 (KHTML, like Gecko) Chrome/24.0.1295.0 Safari/537.15')]
    RE_BUILD_REQUEST = re.compile(r"sendBuildRequest\(\'(.*)\', null, 1\)")
    RE_SERVER_TIME = re.compile(r"<th>Server time </th>\s*<th.*>(.*)</th>")
    RE_RESOURCE = re.compile(r"(?:<font >)?(\d+)(?:/\d*)?(?:</font>)?")
    RE_BUILD_LVL = re.compile(r"(?: \(level (\d*)\))|<br />")
    RE_IN_CONSTRUCTION = re.compile(r"\d+.: (.*) (\d+)")
    RE_SHIP_COST = re.compile(
        r"(\w*): <b style=\"color:\w*;\">(?: <t title=\"-(?:\d|\.)+\"><span class=\"noresources\">)?((?:\d|\.)+)")

    # ship -> ship id on the page
    SHIPS = {
        'lm': '204',
        'hm': '205',
        'cr': '206',
        'ow': '207',
        'pn': '215',
        'bb': '211',
        'ns': '213',
        'gs': '214',
        'lt': '202',
        'dt': '203',
        'cs': '208',
        'rc': '209',
        'ss': '210'
    }

    # mission ids
    MISSIONS = {
        'Attack': '1',
        'Transport': '3',
        'Hold Position': '5',
        'Expedition': '15',
        'Collect': '8'
    }

    TARGETS = {
        'Planet': '1',
        'Moon': '3',
        'Debris': '2'
    }

    def __init__(self, username, password, server):
        self.username = username
        self.password = password
        self.logged_in = False

        self._prepare_logger()
        self._prepare_browser()
        farms = options['farming']['farms']
        self.farm_no = randint(0, len(farms)-1) if farms else 0

        self.MAIN_URL = 'http://labdcc.fceia.unr.edu.ar/~jgalat/game.php'
        server=server.replace('http://','')
        if server[-1]=='/':
            server=server[:-1]
        self.MAIN_URL = 'http://'+server+'/game.php'
        self.PAGES = {
            'main':        self.MAIN_URL + '?page=overview',
            'buildings':   self.MAIN_URL + '?page=buildings',
            'station':     self.MAIN_URL + '?page=station',
            'research':    self.MAIN_URL + '?page=buildings&mode=research',
            'shipyard':    self.MAIN_URL + '?page=buildings&mode=fleet',
            'defense':     self.MAIN_URL + '?page=defense',
            'fleet':       self.MAIN_URL + '?page=fleet',
            'galaxy':      self.MAIN_URL + '?page=galaxy',
            'galaxyCnt':   self.MAIN_URL + '?page=galaxyContent',
            'events':      self.MAIN_URL + '?page=eventList',
        }
        self.planets = []
        self.moons = []
        self.active_attacks = []

        self.fleet_slots = 0
        self.active_fleets = 0

        self.server_time = self.local_time = datetime.now()
        self.time_diff = 0
        self.emergency_sms_sent = False
        self.transport_manager = TransportManager()
        self.sim = Sim()

    def _get_url(self, page, planet=None):
        url = self.PAGES[page]
        if planet is not None:
            url += '&cp=%s' % planet.id
        return url

    def _prepare_logger(self):
        self.logger = logging.getLogger("mechanize")
        fh = RotatingFileHandler('bot.log', maxBytes=100000, backupCount=5)
        sh = logging.StreamHandler()
        fmt = logging.Formatter(fmt='%(asctime)s %(levelname)s %(message)s',
                                datefmt='%m-%d, %H:%M:%S')
        fh.setFormatter(fmt)
        sh.setFormatter(fmt)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(fh)
        self.logger.addHandler(sh)
        self.logger.propagate = False

    def _prepare_browser(self):
        self.br = mechanize.Browser()
        self.br.set_handle_equiv(True)
        self.br.set_handle_redirect(True)
        self.br.set_handle_referer(True)
        self.br.set_handle_robots(False)
        self.br.addheaders = self.HEADERS

    def _parse_build_url(self, js):
        """
        convert: `sendBuildRequest('url', null, 1)`; into: `url`
        """
        return self.RE_BUILD_REQUEST.findall(js)[0]

    def _parse_server_time(self, content):
        return self.RE_SERVER_TIME.findall(content)[0]

    def get_mother(self):
        for p in self.planets:
            if p.mother:
                return p
        return p[0] if self.planets else None

    def get_closest_planet(self, p):
        def min_dist(p, d):
            return d
        _, d, _ = p.split(":")
        return sorted([(planet, planet.get_distance(p))
                      for planet in self.planets], key=lambda x: x[1])[0][0]

    def find_planet(self, name=None, coords=None, id=None, is_moon=None):
        if is_moon:
            planets = self.moons
        else:
            planets = self.planets
        for p in planets:
            if name == p.name or coords == p.coords or id == p.id:
                return p

    def get_safe_planet(self, planet):
        '''
        Get first planet which is not under attack and isn't `planet`
        '''
        unsafe_planets = [a.planet for a in self.active_attacks]
        for p in self.planets:
            if not p in unsafe_planets and p != planet:
                return p
        # no safe planets! go to mother
        return self.planets[0]

    def login(self, username=None, password=None):
        username = username or self.username
        password = password or self.password

        try:
            resp = self.br.open(self.MAIN_URL, timeout=10)
            soup = BeautifulSoup(resp)
        except:
            return False

        # no redirect on main page == user logged in
        if resp.geturl() == self.MAIN_URL:
            self.logged_in = True
            self.logger.info('Logged as: %s' % username)
            return True

        self.logger.info('Logging in..')
        self.br.select_form(nr=0)
        self.br.form['username'] = username
        self.br.form['password'] = password
        self.br.submit()
        if self.br.geturl().startswith(self.MAIN_URL):
            self.logged_in = True
            self.logger.info('Logged as: %s' % username)
            return True
        else:
            self.logged_in = False
            self.logger.error('Login failed!')
            return False

    def calc_time(self, resp):

        try:
            self.server_time = datetime.strptime(
                str(date.today().year) + ' ' + self._parse_server_time(resp),
                "%Y %a %b %d %H:%M:%S")
        except:
            self.logger.error('Exception while calculating time')
        else:
            self.local_time = n = datetime.now()
            self.time_diff = self.server_time - self.local_time

            self.logger.info('Server time: %s, local time: %s' %
                             (self.server_time, self.local_time))

    def fetch_planets(self):
        self.logger.info('Fetching planets..')
        resp = self.br.open(self.PAGES['main']).read()
        open("main.html", "w").write(resp)
        self.calc_time(resp)
        soup = BeautifulSoup(resp)
        self.planets = []
        self.moons = []
        try:
            for i, c in enumerate(soup.find('select').findAll('option')):
                url = c['value']
                name, coords = c.contents[0].split('&nbsp;')[0:2]
                p = Planet('1', name, coords[1:-1], url, False)
                if i == 0:
                    p.mother = True
                self.planets.append(p)
                     #p_id = int(c.parent.get('id').split('-')[1])
                     # construct_mode = len(
                     #    c.parent.findAll(
                     #        'a',
                     #        'constructionIcon')) != 0

                # check if planet has moon
               # moon = c.parent.find('a', 'moonlink')
               # if moon and 'moonlink' in moon['class']:
               #     url = moon.get('href')
               #     m_id = url.split('cp=')[1]
               #     m = Moon(m_id, coords, url)
               #     self.moons.append(m)
        except:
            self.logger.exception('Exception while fetching planets')
        # else:
        #    self.check_attacks(soup)

    def handle_planets(self):
        for p in iter(self.planets):
            self.upgrade_planet(p)
        self.farm()

    def load_planets(self):
        self.fetch_planets()
        for p in iter(self.planets):
            self.update_planet_shipyard(p)
            self.update_planet_info(p)
            self.update_planet_research(p)
            self.update_planet_fleet(p)
        for m in iter(self.moons):
            self.update_planet_info(m)
            self.update_planet_fleet(m)

    def upgrade_planet(self, planet):
        upds = planet.get_upgrades()
        if 'buildings' in upds:
            for name in upds['buildings']:
                self.logger.info('Building upgrade on %s: %s' % (planet, name))
                self.br.open(planet.buildings[name]['link'])
                # let now transport manager to clear building queue
                # self.transport_manager.update_building(planet)
        if 'researches' in upds:
            for name in upds['researches']:
                self.logger.info('Building research on %s: %s' % (planet, name))
                self.br.open(planet.researches[name]['link'])

        if 'fleets' in upds:
            resp = self.br.open(self._get_url('shipyard', planet))
            soup = BeautifulSoup(resp)
            planet.ships = {}
            formdata = {}
            for c in soup.findAll('td', {'class': 'l'}):
                name = c.find('a').contents[0]
                intxt = c.findNext('th')
                if not intxt:
                    continue
                intxt = intxt.find('input')
                if not intxt:
                    continue
                if name in upds['fleets']:
                    formdata[intxt['name']] = str(upds['fleets'][name])
                    self.logger.info(
                        'Building %d %s on %s' %
                        (upds['fleets'][name], name, planet))
                else:
                    formdata[intxt['name']] = "0"
            self.br.select_form(nr=0)
            for name, value in formdata.iteritems():
                self.br.form[name] = value
            self.br.submit()

        if not upds:
            self.logger.info('Nothing to upgrade or build on %s' % planet)
        return True

    def update_planet_fleet(self, planet):
        planet.ships = {}
        try:
            resp = self.br.open(self._get_url('fleet', planet))
            soup = BeautifulSoup(resp)
            for c in soup.find('form', {'action': 'game.php?page=fleet1'}).findAll('tr')[2:-2]:
                name = c.find('a').contents[0].strip()
                cant = int(c.find('th').findNext('th').contents[0].strip())
                planet.ships[name] = cant
        except:
            self.logger.exception('Exception while updating fleets info')
        s = ', '.join(["%s: %d" % (n, c) for n, c in planet.ships.iteritems()])
        self.logger.info('Ships on %s-> %s' % (planet, s))
        return True

    def update_planet_shipyard(self, planet):
        resp = self.br.open(self._get_url('shipyard', planet))
        soup = BeautifulSoup(resp)
        planet.buyable_fleets = {}
        for c in soup.findAll('td', {'class': 'l'}):
            name = c.find('a').contents[0]
            intxt = c.findNext('th')
            if not intxt:
                continue
            res = self.RE_SHIP_COST.findall("".join(map(str, c.contents)))
            res = {x: int(y.replace('.', '')) for x, y in res}
            planet.buyable_fleets[name] = res
        return True

    def update_planet_info(self, planet):
        resp = self.br.open(self._get_url('buildings', planet))
        soup = BeautifulSoup(resp)
        names = ['Metal', 'Crystal', 'Deuterium', 'Energy']
        try:
            for name, c in zip(names, soup.find(id='resources').findAll(width='90')):
                matched = self.RE_RESOURCE.findall(
                    str(c.contents[0]).replace('.', ''))[0]
                planet.resources[name] = int(matched)
        except:
            self.logger.exception('Exception while updating resources info')
        else:
            self.logger.info('Resources in %s:' % planet)
            s = 'Metal - %(Metal)s, Crystal - %(Crystal)s, Deuterium - %(Deuterium)s'
            self.logger.info(s % planet.resources)

        if planet.is_moon():
            return
        try:
            planet.buildings = {}
            for c in soup.find('table', {'width': '530'}).findAll('td', {'class': 'l'}):
                if len(c.attrs) == 1:
                    childs = c.findChildren()
                    if len(childs) > 2:
                        name = c.find('a').contents[0]
                        exp = self.RE_BUILD_LVL.findall(str(c.contents[2]))
                        if not exp or not exp[0]:
                            lvl = 0
                        else:
                            lvl = int(exp[0])
                        suff_energy = planet.resources[
                            'energy'] - self.sim.upgrade_energy_cost(name, lvl+1) > 0
                        canbuild = c.find('b', {'style': "color:red;"}) is None
                        c2 = c.findNext('td').find('a')
                        if c2 and canbuild:
                            link = c2['href']
                        else:
                            link = None
                        planet.buildings[name] = {
                            'link': link,
                            'level': lvl,
                            'sufficient_energy': suff_energy,
                            'in_construction': False}
            for c in soup.find('table', {'width': '530'}).findAll('td', {'class': 'l'}):
                if len(c.attrs) > 1:
                    name, lvl = self.RE_IN_CONSTRUCTION.findall(
                        str(c.contents[0]))[0]
                    planet.buildings[name].pop('link', None)
                    planet.buildings[name]['level'] = max(
                        planet.buildings[name]['level'],
                        int(lvl))
                    planet.buildings[name]['in_construction'] = True
        except:
            self.logger.exception('Exception while reloading buildings info')
            return False
        else:
            self.logger.info('%s buildings were reloaded' % planet)
        return True

    def update_planet_research(self, planet):
        resp = self.br.open(self._get_url('research', planet))
        soup = BeautifulSoup(resp)
        if planet.is_moon():
            return
        try:
            planet.researches = {}
            for c in soup.find('table', {'width': '530'}).findAll('td', {'class': 'l'}):
                if len(c.attrs) == 1:
                    childs = c.findChildren()
                    if len(childs) > 2:
                        name = c.find('a').contents[0]
                        exp = self.RE_BUILD_LVL.findall(str(c.contents[2]))
                        if not exp or not exp[0]:
                            lvl = 0
                        else:
                            lvl = int(exp[0])
                        canbuild = c.find('b', {'style': "color:red;"}) is None
                        c2 = c.findNext('th', {'class': 'l'}).find('a')
                        if c2 and canbuild:
                            link = c2['href']
                        else:
                            link = None
                        planet.researches[name] = {
                            'link': link,
                            'level': lvl,
                            'in_construction': False}
        except:
            self.logger.exception('Exception while reloading researches info')
            return False
        else:
            self.logger.info('%s researches were reloaded' % planet)
        return True

    def transport_resources(self):
        tasks = self.transport_manager.find_dest_planet(self.planets)
        if tasks is None:
            return False
        self.logger.info(self.transport_manager.get_summary())
        for task in iter(tasks):
            self.logger.info(
                'Transport attempt from: %s, to: %s with resources %s' %
                (task['from'], task['where'], task['resources']))
            result = self.send_fleet(
                task['from'],
                task['where'].coords,
                fleet=task['from'].get_fleet_for_resources(task['resources']),
                resources=task['resources'],
                mission='transport'
            )
            if result:
                self.transport_manager.update_sent_resources(task['resources'])
                self.logger.info(
                    'Resources sent: %s, resources needed: %s' %
                    (task['resources'], self.transport_manager.get_resources_needed()))

        return True

    def build_defense(self, planet):
        """
        Build defense for all resources on the planet
        1. plasma
        2. gauss
        3. heavy cannon
        4. light cannon
        5. rocket launcher
        """
        url = self._get_url('defense', planet)
        resp = self.br.open(url)
        for t in ('406', '404', '403', '402', '401'):
            self.br.select_form(name='form')
            self.br.form.new_control('text', 'menge', {'value': '100'})
            self.br.form.fixup()
            self.br['menge'] = '100'

            self.br.form.new_control('text', 'type', {'value': t})
            self.br.form.fixup()
            self.br['type'] = t

            self.br.form.new_control('text', 'modus', {'value': '1'})
            self.br.form.fixup()
            self.br['modus'] = '1'

            self.br.submit()

    def get_player_status(self, destination, origin_planet=None):
        if not destination:
            return

        status = {}
        origin_planet = origin_planet or self.get_closest_planet(destination)
        galaxy, system, position = destination.split(':')

        url = self._get_url('galaxyCnt', origin_planet)
        data = urlencode({'galaxy': galaxy, 'system': system})
        resp = self.br.open(url, data=data)
        soup = BeautifulSoup(resp)

        soup.find(id='galaxytable')
        planets = soup.findAll('tr', {'class': 'row'})
        target_planet = planets[int(position)-1]
        name_el = target_planet.find('td', 'playername')
        status['name'] = name_el.find('span').text

        status['inactive'] = 'inactive' in name_el.get('class', '')
        return status

    def find_inactive_nearby(self, planet, radius=15):

        self.logger.info("Searching idlers near %s in radius %s"
                         % (planet, radius))

        nearby_systems = planet.get_nearby_systems(radius)
        idlers = []

        for system in nearby_systems:
            galaxy, system = system.split(":")
            url = self._get_url('galaxyCnt', planet)
            data = urlencode({'galaxy': galaxy, 'system': system})
            resp = self.br.open(url, data=data)
            soup = BeautifulSoup(resp)

            galaxy_el = soup.find(id='galaxytable')
            planets = galaxy_el.findAll('tr', {'class': 'row'})
            for pl in planets:
                name_el = pl.find('td', 'playername')
                debris_el = pl.find('td', 'debris')
                inactive = 'inactive' in name_el.get('class', '')
                debris_not_found = 'js_no_action' in debris_el.get('class', '')
                if not inactive or not debris_not_found:
                    continue
                position = pl.find('td', 'position').text
                coords = "%s:%s:%s" % (galaxy, system, position)
                player_id = name_el.find('a').get('rel')

                player_info = soup.find(id=player_id)
                rank_el = player_info.find('li', 'rank')

                if not rank_el:
                    continue

                rank = int(rank_el.find('a').text)
                if rank > 4000 or rank < 900:
                    continue

                idlers.append(coords)
                time.sleep(2)

        return idlers

    def find_inactives(self):

        inactives = []
        for p in self.planets:
            try:
                idlers = self.find_inactive_nearby(p)
                self.logger.info(" ".join(idlers))
                inactives.extend(idlers)
            except Exception as e:
                self.logger.exception(e)
                continue
            time.sleep(5)

        self.logger.info(" ".join(inactives))
        self.inactives = list(set(inactives))
        self.logger.info(inactives)

    def send_fleet(self, origin_planet, destination, fleet={}, resources={},
                   mission='Attack', target='Planet', speed=None, holdingtime=None):
        if origin_planet.coords == destination:
            self.logger.error('Cannot send fleet to the same planet')
            return False
        self.logger.info('Sending fleet from %s to %s (%s)'
                         % (origin_planet, destination, mission))
        try:
            resp = self.br.open(self._get_url('fleet', origin_planet))
            try:
                self.br.select_form(
                    predicate=lambda f: 'action' in f.attrs and f.attrs
                    ['action'] == 'game.php?page=fleet1')
            except mechanize.FormNotFoundError:
                self.logger.info('No available ships on the planet')
                return False
            #resp=open("samples/fleet.html", "r").read()
            soup = BeautifulSoup(resp)
            sended = set()
            for c in soup.find('form', {'action': 'game.php?page=fleet1'}).findAll('tr')[2:-2]:
                name = c.find('a').contents[0].strip()
                if name in fleet:
                    inp = c.find('input')['name'].strip()
                    sended.add(name)
                    self.br.form[inp] = str(fleet[name])

            for name in fleet.iterkeys():
                if name not in sended:
                    self.logger.info("Couldn't send all ships to mission")
                    return False
            self.br.submit()
            try:
                self.br.select_form(
                    predicate=lambda f: 'action' in f.attrs and f.attrs
                    ['action'] == 'game.php?page=fleet2')
            except mechanize.FormNotFoundError:
                self.logger.info('Error while sending ships, fleet2')
                return False

            galaxy, system, position = destination.split(':')
            self.br.form['galaxy'] = galaxy
            self.br.form['system'] = system
            self.br.form['planet'] = position
            self.br.form['planettype'] = [self.TARGETS[target]]
            if speed:
                self.br.form['speed'][0] = str(floor(int(speed)/10))
            self.br.submit()

            try:
                self.br.select_form(
                    predicate=lambda f: 'action' in f.attrs and f.attrs
                    ['action'] == 'game.php?page=fleet3')
            except mechanize.FormNotFoundError:
                self.logger.info('Error while sendind ships, fleet 3')
                return False
            self.br.form['mission'] = [self.MISSIONS[mission]]
            if holdingtime:
                self.br.form['holdingtime'] = [str(holdingtime)]
            if 'Metal' in resources:
                self.br.form['resource1'] = str(resources['Metal'])
            if 'Crystal' in resources:
                self.br.form['resource2'] = str(resources['Crystal'])
            if 'Deuterium' in resources:
                self.br.form['resource3'] = str(resources['Deuterium'])
            self.br.submit()
            last_response = self.br.response() # This is returned by br.open(...) too
            print last_response.geturl()
            print last_response.info()
        except Exception as e:
            self.logger.exception(e)
            return False
        return True

    def send_message(self, url, player, subject, message):
        self.logger.info('Sending message to %s: %s' % (player, message))
        self.br.open(url)
        self.br.select_form(nr=0)
        self.br.form['betreff'] = subject
        self.br.form['text'] = message
        self.br.submit()

    def send_sms(self, msg):
        from smsapigateway import SMSAPIGateway
        try:
            SMSAPIGateway().send(msg)
        except Exception as e:
            self.logger.exception(str(e))

    def handle_attacks(self):
        attack_opts = options['attack']
        send_sms = bool(options['sms']['send_sms'])

        for a in self.active_attacks:
            if a.is_dangerous():
                self.logger.info('Handling attack: %s' % a)
                if not a.planet.is_moon():
                    self.build_defense(a.planet)
                if send_sms and not a.sms_sent:
                    self.send_sms(a.get_sms_text())
                    a.sms_sent = True
                if send_sms and not a.message_sent:
                    self.send_message(
                        a.message_url,
                        a.player,
                        attack_opts['message_topic'],
                        a.get_random_message())
                    a.message_sent = True
                self.fleet_save(a.planet)

    def check_attacks(self, soup):
        alert = soup.find(id='attack_alert')
        if not alert:
            self.logger.exception('Check attack failed')
            return
        if 'noAttack' in alert.get('class', ''):
            self.logger.info('No attacks')
            self.active_attacks = []
        else:
            self.logger.info('ATTACK!')
            resp = self.br.open(self.PAGES['events'])
            soup = BeautifulSoup(resp)
            hostile = False
            try:
                for tr in soup.findAll('tr'):
                    countDown = tr.find('td', 'countDown')
                    if countDown and 'hostile' in countDown.get('class', ''):
                        hostile = True
                        # First: check if attack was noticed
                        if tr.get('id'):
                            attack_id = tr.get('id').split('-')[1]
                        elif countDown.get('id'):
                            attack_id = countDown.get('id').split('-')[2]
                        if not attack_id or attack_id in [a.id for a in self.active_attacks]:
                            continue
                        try:
                            # Attack first discovered: save attack info
                            arrivalTime = tr.find(
                                'td',
                                'arrivalTime').text.split(' ')[0]
                            coordsOrigin = tr.find('td', 'coordsOrigin')
                            if coordsOrigin:
                                if coordsOrigin.find('a'):
                                    coordsOrigin = coordsOrigin.find(
                                        'a').text.strip()[1:-1]
                            destCoords = tr.find('td', 'destCoords')
                            if destCoords:
                                destCoords = destCoords.find(
                                    'a').text.strip()[1:-1]
                            originFleet = tr.find('td', 'originFleet')
                            detailsFleet = int(
                                tr.find(
                                    'td',
                                    'detailsFleet').span.text.replace(
                                    '.',
                                    ''))
                            player_info = originFleet.find('a')
                            message_url = player_info.get('href')
                            player = player_info.get('data-player-name')
                            is_moon = False  # TODO!
                            planet = self.find_planet(
                                coords=destCoords,
                                is_moon=is_moon)
                            a = Attack(
                                planet,
                                attack_id,
                                arrivalTime,
                                coordsOrigin,
                                destCoords,
                                detailsFleet,
                                player,
                                message_url)

                            self.active_attacks.append(a)
                        except Exception as e:
                            self.logger.exception(e)
                            self.send_sms('ATTACKEROR')
                if not hostile:
                    self.active_attacks = []
            except Exception as e:
                self.logger.exception(e)

    def fleet_save(self, p):
        if not p.has_ships():
            return
        fleet = p.ships
        # recyclers are staying!
        #fleet['rc'] = 0
        self.logger.info('Making fleet save from %s' % p)
        self.send_fleet(p,
                        self.get_safe_planet(p).coords,
                        fleet=fleet,
                        mission='Hold Position',
                        speed=10,
                        resources={'metal': p.resources['metal']+500,
                                   'crystal': p.resources['crystal']+500,
                                   'deuterium': p.resources['deuterium']+500})

    def collect_debris(self, p):
        if not p.has_ships():
            return
        self.logger.info(
            'Collecting debris from %s using %s recyclers' %
            (p, p.ships['rc']))
        self.send_fleet(p,
                        p.coords,
                        fleet={'rc': p.ships['rc']},
                        mission='collect',
                        target='debris')

    def send_expedition(self):
        expedition = options['expedition']
        planets = expedition['planets'].split(' ')
        random.shuffle(planets)
        for coords in planets[:3]:
            planet = self.find_planet(coords=coords)
            if planet:
                galaxy, system, position = planet.coords.split(':')
                expedition_coords = '%s:%s:16' % (galaxy, system)
                self.send_fleet(
                    planet,
                    expedition_coords,
                    fleet={
                        expedition['ships_kind']: expedition['ships_number']},
                    mission='expedition')

    
    def farm(self):
        if options['farming'].has_key('enabled') and options['farming']['enabled'].strip().lower() not in ['true','yes','si','1','y','s']:
            return
        farms =[s.strip().split(' ')[0] for s in  options['farming']['farms'].split(',')]
        if not farms or not farms[0]:
            return
        ships_kind = options['farming']['ships_kind']
        ships_number = options['farming']['ships_number']
        next_farm = int(options['farming']['next_farm'])  % len(farms)

        farm = farms[next_farm]
        #if not self.get_player_status(farm)['inactive']:
        #    self.logger.error('farm %s seems not to be inactive!', farm)
        #    return
        if self.send_fleet(
            self.get_closest_planet(farm),
            farm,
            fleet={ships_kind: ships_number}
        ):
            next_farm = (next_farm+1) % len(farms)
            options.change_item('farming', 'next_farm', str(next_farm))


    def sleep(self):
        sleep_options = options['general']
        sleep_time = randint(
            0, int(sleep_options['seed']))+int(sleep_options['check_interval'])
        self.logger.info('Sleeping for %s secs' % sleep_time)
        if self.active_attacks:
            sleep_time = 60
        time.sleep(sleep_time)

    def stop(self):
        self.logger.info('Stopping bot')
        os.unlink(self.pidfile)

    def interactive(self):
        self.pid = str(os.getpid())
        self.pidfile = 'bot.pid'
        file(self.pidfile, 'w').write(self.pid)
        if not self.login():
            self.logger.error('Login failed!')
        self.load_planets()

    def start(self):
        self.logger.info('Starting bot')
        self.pid = str(os.getpid())
        self.pidfile = 'bot.pid'
        file(self.pidfile, 'w').write(self.pid)

        # main loop
        while True:
            if self.login():
                try:
                    self.load_planets()
                    self.handle_planets()
                    # self.find_inactives()
                    # if not self.active_attacks:
                    #    if True or not self.transport_resources():
                    #        self.send_expedition()
                    #        self.farm()
                    #        self.farm()
                    # else:
                    #    self.handle_attacks()

                except Exception as e:
                    self.logger.exception(e)
                    # self.stop()
                    # return
            else:
                self.logger.error('Login failed!')
                # self.stop()
                # return
            self.sleep()


def st():
    credentials = options['credentials']
    bot = Bot(credentials['username'], credentials['password'], credentials['server'])
    bot.interactive()
    return bot

if __name__ == "__main__":
    credentials = options['credentials']
    bot = Bot(credentials['username'], credentials['password'], credentials['server'])
    bot.start()
