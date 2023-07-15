###############################################################################
# WaterTAP Copyright (c) 2021, The Regents of the University of California,
# through Lawrence Berkeley National Laboratory, Oak Ridge National
# Laboratory, National Renewable Energy Laboratory, and National Energy
# Technology Laboratory (subject to receipt of any required approvals from
# the U.S. Dept. of Energy). All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and license
# information, respectively. These files are also available online at the URL
# "https://github.com/watertap-org/watertap/"
#
###############################################################################

import os
import sys
import re

import pandas as pd
import numpy as np

from io import StringIO
import matplotlib.pyplot as plt

from pyomo.environ import Var, Constraint, Suffix, units as pyunits

from idaes.core import declare_process_block_class
import idaes.core.util.scaling as iscale
from idaes.core.surrogate.surrogate_block import SurrogateBlock
from idaes.core.surrogate.pysmo_surrogate import PysmoRBFTrainer, PysmoSurrogate
from idaes.core.surrogate.sampling.data_utils import split_training_validation

from watertap_contrib.seto.core import SolarEnergyBaseData

__author__ = "Matthew Boyd, Kurban Sitterley"


@declare_process_block_class("TroughSurrogate")
class TroughSurrogateData(SolarEnergyBaseData):
    """
    Surrogate model for trough.
    """

    CONFIG = SolarEnergyBaseData.CONFIG()

    def build(self):
        super().build()

        self.scaling_factor = Suffix(direction=Suffix.EXPORT)
        self._tech_type = "trough"

        self.heat_load = Var(
            initialize=1000,
            bounds=[100, 1000],
            units=pyunits.MW,
            doc="Rated plant heat capacity in MWt",
        )

        self.hours_storage = Var(
            initialize=20,
            bounds=[0, 26],
            units=pyunits.hour,
            doc="Rated plant hours of storage",
        )

        self.heat_annual = Var(
            initialize=1000,
            units=pyunits.kWh,
            doc="Annual heat generated by trough",
        )

        self.electricity_annual = Var(
            initialize=20,
            units=pyunits.kWh,
            doc="Annual electricity consumed by trough",
        )

        stream = StringIO()
        oldstdout = sys.stdout
        sys.stdout = stream

        self.surrogate_inputs = [self.heat_load, self.hours_storage]
        self.surrogate_outputs = [self.heat_annual, self.electricity_annual]

        self.input_labels = ["heat_load", "hours_storage"]
        self.output_labels = ["heat_annual", "electricity_annual"]

        self.surrogate_file = os.path.join(
            os.path.dirname(__file__), "trough_surrogate.json"
        )
        self.surrogate_blk = SurrogateBlock(concrete=True)
        self.surrogate = PysmoSurrogate.load_from_file(self.surrogate_file)
        self.surrogate_blk.build_model(
            self.surrogate,
            input_vars=self.surrogate_inputs,
            output_vars=self.surrogate_outputs,
        )

        self.heat_constraint = Constraint(
            expr=self.heat_annual
            == self.heat * pyunits.convert(1 * pyunits.year, to_units=pyunits.hour)
        )

        self.electricity_constraint = Constraint(
            expr=self.electricity_annual
            == self.electricity
            * pyunits.convert(1 * pyunits.year, to_units=pyunits.hour)
        )

        # Revert back to standard output
        sys.stdout = oldstdout

        self.dataset_filename = os.path.join(
            os.path.dirname(__file__), "data/trough_data.pkl"
        )
        self.n_samples = 100
        self.training_fraction = 0.8

    def calculate_scaling_factors(self):

        if iscale.get_scaling_factor(self.hours_storage) is None:
            sf = iscale.get_scaling_factor(self.hours_storage, default=1)
            iscale.set_scaling_factor(self.hours_storage, sf)

        if iscale.get_scaling_factor(self.heat_load) is None:
            sf = iscale.get_scaling_factor(self.heat_load, default=1e-2, warning=True)
            iscale.set_scaling_factor(self.heat_load, sf)

        if iscale.get_scaling_factor(self.heat_annual) is None:
            sf = iscale.get_scaling_factor(self.heat_annual, default=1e-4, warning=True)
            iscale.set_scaling_factor(self.heat_annual, sf)

        if iscale.get_scaling_factor(self.heat) is None:
            sf = iscale.get_scaling_factor(self.heat, default=1e-4, warning=True)
            iscale.set_scaling_factor(self.heat, sf)

        if iscale.get_scaling_factor(self.electricity_annual) is None:
            sf = iscale.get_scaling_factor(
                self.electricity_annual, default=1e-3, warning=True
            )
            iscale.set_scaling_factor(self.electricity_annual, sf)

        if iscale.get_scaling_factor(self.electricity) is None:
            sf = iscale.get_scaling_factor(self.electricity, default=1e-3, warning=True)
            iscale.set_scaling_factor(self.electricity, sf)

    def initialize_build(self):
        super().initialize()


    def _create_rbf_surrogate(self, data_training=None, output_filename=None):

        if data_training is None:
            self._get_surrogate_data()
        else:
            self.data_training = data_training

        # Capture long output
        stream = StringIO()
        oldstdout = sys.stdout
        sys.stdout = stream

        # Create PySMO trainer object
        self.trainer = PysmoRBFTrainer(
            input_labels=self.input_labels,
            output_labels=self.output_labels,
            training_dataframe=self.data_training,
        )

        # Set PySMO options
        self.trainer.config.basis_function = "gaussian"  # default = gaussian
        self.trainer.config.solution_method = "algebraic"  # default = algebraic
        self.trainer.config.regularization = True  # default = True

        # Train surrogate
        self.rbf_train = self.trainer.train_surrogate()

        # Remove autogenerated 'solution.pickle' file
        try:
            os.remove("solution.pickle")
        except FileNotFoundError:
            pass
        except Exception as e:
            raise e

        # Create callable surrogate object
        xmin, xmax = [100, 0], [1000, 26]
        self.input_bounds = {
            self.input_labels[i]: (xmin[i], xmax[i])
            for i in range(len(self.input_labels))
        }
        self.rbf_surr = PysmoSurrogate(
            self.rbf_train, self.input_labels, self.output_labels, self.input_bounds
        )

        # Save model to JSON
        if output_filename is not None:
            model = self.rbf_surr.save_to_file(output_filename, overwrite=True)

        # Revert back to standard output
        sys.stdout = oldstdout

    def _get_surrogate_data(self, return_data=False):
        self.pickle_df = pd.read_pickle(self.dataset_filename)
        self.data = self.pickle_df.sample(n=self.n_samples)
        self.data_training, self.data_validation = split_training_validation(
            self.data, self.training_fraction, seed=len(self.data)
        )
        if return_data:
            return self.data_training, self.data_validation

    def _plot_training_validation(
        self,
        data_training=None,
        data_validation=None,
        surrogate=None,
        surrogate_filename="trough_surrogate.json",
    ):
        if data_training is None and data_validation is None:
            data_training = self.data_training
            data_validation = self.data_validation

        if surrogate is None and surrogate_filename is not None:
            surr_file = os.path.join(os.path.dirname(__file__), surrogate_filename)
            surrogate = PysmoSurrogate.load_from_file(surr_file)
        elif surrogate is None and surrogate_filename is None:
            raise Exception
        else:
            surrogate = self.surrogate

        for output_label in self.output_labels:
            # Output fit metrics and create parity and residual plots
            print(
                "\n{label}: \n\tR-squared: {r2} \n\tRMSE: {rmse}".format(
                    label=output_label.replace("_", " ").title(),
                    r2=surrogate._trained._data[output_label].model.R2,
                    rmse=surrogate._trained._data[output_label].model.rmse,
                )
            )
            training_output = surrogate.evaluate_surrogate(
                data_training[self.input_labels]
            )
            label = re.sub(
                "[^a-zA-Z0-9 \n\.]", " ", output_label.title()
            )  # keep alphanumeric chars and make title case
            self._parity_residual_plots(
                true_values=np.array(data_training[output_label]),
                modeled_values=np.array(training_output[output_label]),
                label=label + " - Training",
            )

            # Validate model using validation data
            validation_output = surrogate.evaluate_surrogate(
                data_validation[self.input_labels]
            )
            self._parity_residual_plots(
                true_values=np.array(data_validation[output_label]),
                modeled_values=np.array(validation_output[output_label]),
                label=label + " - Validation",
            )

    def _parity_residual_plots(
        self,
        true_values,
        modeled_values,
        label=None,
        figx=9,
        figy=5,
        axis_fontsize=12,
        title_fontsize=15,
    ):

        fig1 = plt.figure(figsize=(figx, figy), tight_layout=True)
        if label is not None:
            fig1.suptitle(label, fontsize=title_fontsize)
        ax = fig1.add_subplot(121)
        ax.plot(true_values, true_values, "-")
        ax.plot(true_values, modeled_values, "o")
        ax.set_xlabel(r"True data", fontsize=axis_fontsize)
        ax.set_ylabel(r"Surrogate values", fontsize=axis_fontsize)
        ax.set_title(r"Parity plot", fontsize=axis_fontsize)

        ax2 = fig1.add_subplot(122)
        ax2.plot(
            true_values,
            true_values - modeled_values,
            "s",
            mfc="w",
            mec="m",
            ms=6,
        )
        ax2.axhline(y=0, xmin=0, xmax=1)
        ax2.set_xlabel(r"True data", fontsize=axis_fontsize)
        ax2.set_ylabel(r"Residuals", fontsize=axis_fontsize)
        ax2.set_title(r"Residual plot", fontsize=axis_fontsize)

        plt.show()
