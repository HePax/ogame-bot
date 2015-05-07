import math

class Sim(object):
	FIRST_COST = {
		'Metal Mine': {
			'metal':    60,
			'crystal':  15,
			'deuterium': 0,
		},
		'Crystal Mine': {
			'metal':   48,
			'crystal': 24,
			'deuterium': 0
		},
		'Deuterium Synthesizer':{
			'metal':   225,
			'crystal':  75,
			'deuterium': 0
		},
		'Solar Plant': {
			'metal':   75,
			'crystal': 30,
			'deuterium': 0
		},
		'Fusion Plant': {
			'metal': 900,
			'crystal': 360,
			'deuterium': 180
		}
	}
	FACTORS = {
		'Metal Mine': 1.5,
		'Crystal Mine': 1.6,
		'Deuterium Synthesizer': 1.5,
		'Solar Plant': 1.5,
		'Fusion Plant': 1.8
	}

	ENERGY_COST_FACTORS = {
		'Metal Mine': 10,
		'Crystal Mine': 10,
		'Deuterium Synthesizer': 20
	}

	def _calc_building_cost(self, what, level):
		assert what in ('Metal Mine', 'Crystal Mine', 'Deuterium Synthesizer', 'Solar Plant', 'Fusion Plant')
		return {
			'metal': int(self.FIRST_COST[what]['metal'] * (self.FACTORS[what] ** (level - 1))),
			'crystal': int(self.FIRST_COST[what]['crystal'] * (self.FACTORS[what] ** (level - 1))),
			'deuterium': int(self.FIRST_COST[what]['deuterium'] * (self.FACTORS[what] ** (level - 1))),
		}

	def _calc_energy_cost(self, what, level):
		return math.floor(self.ENERGY_COST_FACTORS[what] * level * 1.1 ** level) + 1

	def upgrade_energy_cost(self, what, to_level):
		try:
			return self._calc_energy_cost(what, to_level) - self._calc_energy_cost(what, to_level-1)
		except KeyError:
			return -10000000

	def cost_solar_plant(self, level):
		return self._calc_building_cost('Solar Plant', level)

	def cost_metal_mine(self, level):
		return self._calc_building_cost('Metal Mine', level)

	def cost_crystal_mine(self, level):
		return self._calc_building_cost('Crystal Mine', level)

	def cost_deuterium_mine(self, level):
		return self._calc_building_cost('Deuterium Synthesizer', level)

	def get_cost(self, what, level):
		return self._calc_building_cost(what, level)

	def get_total_transport_capacity(self, ships):
		return (ships['lt'] * 5000) + (ships['dt'] * 25000)

#test
if __name__ == "__main__":
	s = Sim()
