import pyomo.environ as pyo
from watertap.costing.util import register_costing_parameter_block
from watertap_contrib.seto.costing.util import (
    make_capital_cost_var,
    make_fixed_operating_cost_var,
)


def build_lt_med_surrogate_cost_param_block(blk):

    costing = blk.parent_block()

    blk.cost_fraction_evaporator = pyo.Var(
        initialize=0.4,
        units=pyo.units.dimensionless,
        bounds=(0, None),
        doc="Cost fraction of the evaporator",
    )

    blk.cost_fraction_maintenance = pyo.Var(
        initialize=0.02,
        units=pyo.units.dimensionless,
        bounds=(0, None),
        doc="Fraction of capital cost for maintenance",
    )

    blk.cost_fraction_insurance = pyo.Var(
        initialize=0.005,
        units=pyo.units.dimensionless,
        bounds=(0, None),
        doc="Fraction of capital cost for insurance",
    )

    blk.cost_storage_per_kwh = pyo.Var(
        initialize=26,
        units=costing.base_currency / pyo.units.kWh,
        bounds=(0, None),
        doc="Cost of thermal storage per kWh",
    )

    blk.cost_chemicals_per_vol_dist = pyo.Var(
        initialize=0.04,
        units=costing.base_currency / pyo.units.m**3,
        bounds=(0, None),
        doc="Cost of chemicals per m3 distillate",
    )

    blk.cost_labor_per_vol_dist = pyo.Var(
        initialize=0.033,
        units=costing.base_currency / pyo.units.m**3,
        bounds=(0, None),
        doc="Cost of labor per m3 distillate",
    )

    blk.cost_misc_per_vol_dist = pyo.Var(
        initialize=0.033,
        units=costing.base_currency / pyo.units.m**3,
        bounds=(0, None),
        doc="Cost of labor per m3 distillate",
    )

    blk.cost_disposal_per_vol_brine = pyo.Var(
        initialize=0.02,
        units=costing.base_currency / pyo.units.m**3,
        bounds=(0, None),
        doc="Cost of disposal per m3 brine",
    )

    blk.specific_electric_energy_consumption = pyo.Var(
        initialize=1.5,
        units=pyo.units.kWh / pyo.units.m**3,
        bounds=(0, None),
        doc="Specific electric energy consumption",
    )

    # MED system cap = [6291 * dist_flow ** -0.135 * (1 - f_hex)] + [f_hex * (hex_area / 302.01) ** 0.8

    blk.med_sys_A_coeff = pyo.Var(
        initialize=6291,
        units=pyo.units.dimensionless,
        doc="LT-MED system capital A coeff",
    )

    blk.med_sys_B_coeff = pyo.Var(
        initialize=-0.135,
        units=pyo.units.dimensionless,
        doc="LT-MED system capital B coeff",
    )

    blk.med_sys_C_coeff = pyo.Var(
        initialize=302.01,
        units=pyo.units.dimensionless,
        doc="LT-MED system capital C coeff",
    )

    blk.med_sys_D_coeff = pyo.Var(
        initialize=0.8,
        units=pyo.units.dimensionless,
        doc="LT-MED system capital D coeff",
    )

    blk.fix_all_vars()


@register_costing_parameter_block(
    build_rule=build_lt_med_surrogate_cost_param_block,
    parameter_block_name="lt_med_surrogate",
)
def cost_lt_med_surrogate(blk):

    lt_med_params = blk.costing_package.lt_med_surrogate
    make_capital_cost_var(blk)
    make_fixed_operating_cost_var(blk)

    lt_med = blk.unit_model
    feed = lt_med.feed_props[0]
    dist = lt_med.distillate_props[0]
    brine = lt_med.brine_props[0]
    base_currency = blk.config.flowsheet_costing_block.base_currency

    blk.system_cost = pyo.Var(
        initialize=100,
        units=base_currency,
        doc="MED system cost",  # what is this actually??
    )

    blk.heat_exchanger_specific_area = pyo.Var(
        initialize=100,
        units=pyo.units.m**2 / (pyo.units.kg / pyo.units.s),
        doc="Specific heat exchanger area",
    )

    blk.thermal_storage_capacity = pyo.Var(
        initialize=5,
        units=pyo.units.kWh,
        doc="Thermal storage capacity",
    )

    blk.hours_thermal_storage = pyo.Var(
        initialize=5,
        units=pyo.units.hr,
        doc="Hours of thermal storage required",
    )

    blk.heat_exchanger_specific_area_constraint = pyo.Constraint(
        expr=blk.heat_exchanger_specific_area
        == pyo.units.convert(
            lt_med.specific_area / feed.dens_mass_phase["Liq"],
            to_units=(pyo.units.m**2 * pyo.units.s) / pyo.units.kg,
        )
    )

    blk.thermal_storage_capacity_constraint = pyo.Constraint(
        expr=blk.thermal_storage_capacity
        == lt_med.thermal_power_requirement * blk.hours_thermal_storage
    )

    blk.capacity = pyo.units.convert(
        dist.flow_vol_phase["Liq"], to_units=pyo.units.m**3 / pyo.units.day
    )

    blk.annual_dist_production = pyo.units.convert(
        dist.flow_vol_phase["Liq"], to_units=pyo.units.m**3 / pyo.units.year
    )

    blk.system_cost_constraint = pyo.Constraint(
        expr=blk.system_cost
        == (
            (
                lt_med_params.med_sys_A_coeff
                * blk.capacity**lt_med_params.med_sys_B_coeff
            )
            * (1 - lt_med_params.cost_fraction_evaporator)
        )
        + (
            lt_med_params.cost_fraction_evaporator
            * (
                (blk.heat_exchanger_specific_area / lt_med_params.med_sys_C_coeff)
                ** lt_med_params.med_sys_D_coeff
            )
        )
    )

    blk.capital_cost_constraint = pyo.Constraint(
        expr=blk.capital_cost
        == blk.system_cost * blk.capacity
        + lt_med_params.cost_storage_per_kwh * blk.thermal_storage_capacity
    )

    blk.fixed_operating_cost_constraint = pyo.Constraint(
        expr=blk.fixed_operating_cost
        == blk.annual_dist_production
        * (
            lt_med_params.cost_chemicals_per_vol_dist
            + lt_med_params.cost_labor_per_vol_dist
            + lt_med_params.cost_misc_per_vol_dist
        )
        + blk.system_cost
        * (
            lt_med_params.cost_fraction_maintenance
            + lt_med_params.cost_fraction_insurance
        )
        + pyo.units.convert(
            brine.flow_vol_phase["Liq"], to_units=pyo.units.m**3 / pyo.units.year
        )
        * lt_med_params.cost_disposal_per_vol_brine
    )
    
    blk.heat_flow = pyo.Expression(
        expr=lt_med.spec_thermal_consumption
        * pyo.units.convert(blk.capacity, to_units=pyo.units.m**3 / pyo.units.hr)
    )
    blk.electricity_flow = pyo.Expression(
        expr=lt_med_params.specific_electric_energy_consumption
        * pyo.units.convert(blk.capacity, to_units=pyo.units.m**3 / pyo.units.hr)
    )

    blk.costing_package.cost_flow(blk.heat_flow, "heat")
    blk.costing_package.cost_flow(blk.electricity_flow, "electricity")
