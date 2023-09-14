# -*- coding: utf-8 -*-
"""
    Class for harmonizing data retrieved from EPA's Water Quality Portal (WQP)
"""
from types import SimpleNamespace
from warnings import warn
import pandas
import pint
from numpy import nan
from harmonize_wq import domains
from harmonize_wq import basis
from harmonize_wq import convert
from harmonize_wq import harmonize 

class WQCharData():
    """
    A class to represent Water Quality Portal results for a specific
    characteristic

    Parameters
    ----------
    df_in : pandas.DataFrame
        DataFrame that will be updated.
    char_val : str
        Expected characteristicName.

    Attributes
    ----------
    df : pandas.DataFrame
        DataFrame with results for the specific characteristic
    c_mask : pandas.Series
        Row conditional (bool) mask to limit df rows to only those for the
        specific characteristic
    col : SimpleNamespace
        Standard df column names for unit_in, unit_out, and measure
    out_col : str
        Column name in df for results, set using char_val
    ureg = pint.UnitRegistry()
        Pint unit registry, starts set to standard unit registry
    units: str
        Units all results in out_col will be converted into. Default units are
        returned from domains.OUT_UNITS[out_col].
    
    Examples
    --------
    Build dataframe to use as input:
    
    >>> from pandas import DataFrame
    >>> from numpy import nan
    >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Temperature, water',],
    ...                 'ResultMeasure/MeasureUnitCode': [nan, nan],
    ...                 'ResultMeasureValue': ['1.0', '10.0',],
    ...                 })
    >>> df
       CharacteristicName  ResultMeasure/MeasureUnitCode ResultMeasureValue
    0          Phosphorus                            NaN                1.0
    1  Temperature, water                            NaN               10.0
    
    >>> wq = harmonize.WQCharData(df, 'Phosphorus')
    >>> wq.df
       CharacteristicName  ResultMeasure/MeasureUnitCode  ... Units  Phosphorus
    0          Phosphorus                            NaN  ...   NaN         1.0
    1  Temperature, water                            NaN  ...   NaN         NaN
    
    [2 rows x 5 columns]
    >>> wq.df.columns
    Index(['CharacteristicName', 'ResultMeasure/MeasureUnitCode',
           'ResultMeasureValue', 'Units', 'Phosphorus'],
          dtype='object')
    """

    def __init__(self, df_in, char_val):
        df_out = df_in.copy()
        # self.check_df(df)
        harmonize.df_checks(df_out)
        c_mask = df_out['CharacteristicName'] == char_val
        self.c_mask = c_mask
        # Deal with units: set out = in
        cols = {'unit_in': 'ResultMeasure/MeasureUnitCode',
                'unit_out': 'Units',
                'measure': 'ResultMeasureValue',
                'basis': 'Speciation', }
        self.col = SimpleNamespace(**cols)
        df_out.loc[c_mask, self.col.unit_out] = df_out.loc[c_mask,
                                                           self.col.unit_in]
        self.df = df_out
        # Deal with values: set out_col = in
        self.out_col = domains.out_col_lookup()[char_val]
        self._coerce_measure()
        self.ureg = pint.UnitRegistry()  # Add standard unit registry
        self.units = domains.OUT_UNITS[self.out_col]

    def _coerce_measure(self):
        """ Identifies bad measure values, and flags them. Copies measure
            values to out_col, with bad measures as NaN.
        """
        df_out = self.df
        c_mask = self.c_mask
        meas_col = self.col.measure

        # Coerce bad measures in series to NaN
        meas_s = pandas.to_numeric(df_out.loc[c_mask, meas_col],
                                   errors='coerce')
        # Create a list of the bad measures in the series
        bad_measures = [df_out.iloc[i][meas_col] for i in meas_s[meas_s.isna()].index]
        for bad_meas in pandas.unique(bad_measures):
            # Flag each unique bad measure one measure (not row) at a time
            if pandas.isna(bad_meas):
                flag = '{}: missing (NaN) result'.format(meas_col)
                cond = c_mask & (df_out[meas_col].isna())
            else:
                flag = '{}: "{}" result cannot be used'.format(meas_col,
                                                               bad_meas)
                cond = c_mask & (df_out[meas_col] == bad_meas)
            # Flag bad measures
            df_out = harmonize.add_qa_flag(df_out, cond, flag)
        df_out[self.out_col] = meas_s  # Return coerced results

        self.df = df_out

    def _unit_mask(self, unit, column=None):
        """Get mask that is characteristic specific (c_mask) and has required units.
        """
        if column:
            # TODO: column for in vs out col, not being used, remove?
            return self.measure_mask() & (self.df[column] == unit)
        return self.measure_mask() & (self.df[self.col.unit_out] == unit)

    def _infer_units(self, flag_col=None):
        """
        Replace missing units with desired unit and add QA_flag about it in df.

        Parameters
        ----------
        flag_col : str, optional
            Column to reference in QA_flags.
            The default None uses WQCharData.col.unit_out instead.
        """
        # QA flag for missing units
        flag = self._unit_qa_flag('MISSING', flag_col)
        # Update mask for missing units
        units_mask = self.c_mask & self.df[self.col.unit_out].isna()
        self.df = harmonize.add_qa_flag(self.df, units_mask, flag)  # Assign flag
        # Update with infered unit
        self.df.loc[units_mask, self.col.unit_out] = self.units
        # Note: .fillna(self.units) is slightly faster but hits datatype issues


    def _unit_qa_flag(self, trouble, flag_col=None):
        """
        Generates a QA_flag flag string for the units column. If unit_col is a copy
        flag_col can specify the original column name for the flag.
    
        Parameters
        ----------
        trouble : str
            Unit problem encountered (e.g., missing).
        flag_col : str, optional
            String to use when referring to the unit_col.
            The default None uses WQCharData.col.unit_out instead.
    
        Returns
        -------
        string
            Flag to use in QA_flag column.
        """
        unit = self.units  # The default unit that replaced the problem unit
        if flag_col:
            return '{}: {} UNITS, {} assumed'.format(flag_col, trouble, unit)
        # Else: Used when flag_col is None, typically the column being checked
        unit_col = self.col.unit_out
        return '{}: {} UNITS, {} assumed'.format(unit_col, trouble, unit)
        
    def _replace_in_col(self, col, old_val, new_val, mask=None):
        """
        Simple string replacement for a column at rows filtered by mask
    
        Parameters
        ----------
        df_in : pandas.DataFrame
            DataFrame that will be updated.
        col : str
            Column of DataFrame to update old_val to _new_val.
        old_val : str
            Old value to replace.
        new_val : str
            New value to use.
        mask : pandas.Series
            Row conditional mask to only update a sub-set of rows.
            The default None uses 'CharacteristicName' mask instead.
    
        Returns
        -------
        df_in : pandas.DataFrame
            Updated DataFrame.
    
        """
        if mask is None:
            mask = self.c_mask
        df_in = self.df
        # Note: Timing is just as fast as long as df isn't copied
        #       Timing for replace vs set unkown
        mask_old = mask & (df_in[col]==old_val)
        #str.replace did not work for short str to long str (over-replaces)
        #df.loc[mask, col] = df.loc[mask, col].str.replace(old_val, new_val)
        df_in.loc[mask_old, col] = new_val  # This should be more explicit
    
        return df_in

    def _dimension_handling(self, unit, quant=None, ureg=None):
        """
        Handles and routes common dimension conversions/contexts
    
        Parameters
        ----------
        unit : str
            Current unit.
        quant : pint.quantity, optional
            Required for conversions to/from moles
        ureg : pint.UnitRegistry, optional
            Unit Registry Object with any custom units defined. The default is None
    
        Returns
        -------
        dict
            Dictionary with old_unit:new_unit.
        list
            List of Mole (substance) units.
    
        """
        units = self.units
        if ureg is None:
            ureg = pint.UnitRegistry()
    
        # Conversion to moles performed a level up from here (class method)
        if ureg(units).check({'[length]': -3, '[mass]': 1}):
            # Convert to density, e.g., '%' -> 'mg/l'
            if ureg(unit).check({'[substance]': 1}):
                if quant:
                    # Moles -> mg/l; dim = ' / l'
                    return {unit: quant + ' / l'}, [quant + ' / l']
                raise ValueError("Pint Quantity required for moles conversions")
            # Else assume it is dimensionless (e.g. unit = 'g/kg')
            return {unit: unit + ' * H2O'}, []
        if ureg(units).dimensionless:
            # Convert to dimensionless, e.g., 'mg/l' -> '%'
            if ureg(unit).check({'[substance]': 1}):
                if quant:
                    # Moles -> g/kg; dim = ' / l / H2O'
                    return {unit: quant + ' / l / H2O'}, [quant + ' / l / H2O']
                raise ValueError("Pint Quantity required for moles conversions")
            # Else assume it is density (e.g. unit = 'mg/l')
            return {unit: unit + ' / H2O'}, []
        warn('WARNING: Unexpected dimensionality')
        return {}, []

    def check_units(self, flag_col=None):
        """
        Checks for bad units that are missing (assumes default_unit) or
        unrecognized as valid by unit registry (ureg). Does not check for units
        in the correct dimensions, or a mistaken identity (e.g. 'deg F'
        recognized as 'degree * farad').

        Parameters
        ----------
        flag_col : str, optional
            Column to reference in QA_flags.
            The default None uses WQCharData.col.unit_out instead.
            
        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> from numpy import nan
        >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Temperature, water', 'Phosphorus',],
        ...                 'ResultMeasure/MeasureUnitCode': [nan, nan, 'Unknown',],
        ...                 'ResultMeasureValue': ['1.0', '67.0', '10',],
        ...                 })
        >>> df
           CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0          Phosphorus                           NaN                1.0
        1  Temperature, water                           NaN               67.0
        2          Phosphorus                       Unknown                 10
        
        Build WQ Characteristic Data object from DataFrame:
        
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        >>> wq.df.Units
        0        NaN
        1        NaN
        2    Unknown
        
        Run check_units method to replace bad or missing units for phosphorus:
    
        >>> wq.check_units()
        UserWarning: WARNING: 'Unknown' UNDEFINED UNIT for Phosphorus
        
        >>> wq.df[['CharacteristicName', 'Units']]
           CharacteristicName Units                                            QA_flag
        0          Phosphorus  mg/l  ResultMeasure/MeasureUnitCode: MISSING UNITS, ...
        1  Temperature, water   NaN                                                NaN
        2          Phosphorus  mg/l  ResultMeasure/MeasureUnitCode: 'Unknown' UNDEF...
        
        Note: it didn't infer units for 'Temperature, water' because wq is Phosphorus specific
        """
        # Replace unit by dict using domain
        self.replace_unit_by_dict(domains.UNITS_REPLACE[self.out_col])

        # Deal with optional args
        if flag_col is None:
            flag_col = self.col.unit_in
        self._infer_units(flag_col=flag_col)

        df_out = self.df

        # Check each unique unit is valid in ureg
        for unit in list(set(df_out.loc[self.c_mask, self.col.unit_out])):
            try:
                self.ureg(unit)
            except pint.UndefinedUnitError:
                # WARNING: Does not catch '%' or bad units in ureg (eg deg F)
                # If bad, flag and replace
                problem = "'{}' UNDEFINED UNIT for {}".format(unit, self.out_col)
                warn("WARNING: " + problem)
                flag = self._unit_qa_flag(problem, flag_col)
                # New mask for bad units
                u_mask = self._unit_mask(unit)
                # Assign flag to bad units
                df_out = harmonize.add_qa_flag(df_out, u_mask, flag)
                df_out.loc[u_mask, self.col.unit_out] = self.units  # Replace w/ default
        self.df = df_out

    def check_basis(self, basis_col='MethodSpecificationName'):
        """
        Determine speciation (basis) for measure.

        Parameters
        ----------
        basis_col : str, optional
            Basis column name. Default is 'MethodSpecificationName' which is
            replaced by 'Speciation', others are updated in place.
        
        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> from numpy import nan
        >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Temperature, water', 'Phosphorus',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/l as P', nan, 'mg/l',],
        ...                 'ResultMeasureValue': ['1.0', '67.0', '10',],
        ...                 'MethodSpecificationName': [nan, nan, 'as PO4',],        
        ...                 })
        >>> df
           CharacteristicName  ... MethodSpecificationName
        0          Phosphorus  ...                     NaN
        1  Temperature, water  ...                     NaN
        2          Phosphorus  ...                  as PO4
        
        [3 rows x 4 columns]
        
        Build WQ Characteristic Data object from DataFrame:
        
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        >>> wq.df.columns
        Index(['CharacteristicName', 'ResultMeasure/MeasureUnitCode',
               'MethodSpecificationName', 'ResultMeasureValue', 'Units', 'Phosphorus'],
              dtype='object')
        
        Run check_basis method to speciation for phosphorus:
        
        >>> wq.check_basis()
        >>> wq.df[['MethodSpecificationName', 'Speciation']]
          MethodSpecificationName  Speciation
        0                     NaN           P
        1                     NaN         NaN
        2                     NaN         PO4
        
        Note where basis was part of ResultMeasure/MeasureUnitCode it has been removed in Units:

        >>> wq.df.iloc[0]
        CharacteristicName               Phosphorus
        ResultMeasure/MeasureUnitCode     mg/l as P
        ResultMeasureValue                      1.0
        MethodSpecificationName                 NaN
        Units                                  mg/l
        Phosphorus                              1.0
        Speciation                                P
        Name: 0, dtype: object
        """
        c_mask = self.c_mask

        # Check for Method Specification column
        harmonize.df_checks(self.df, [basis_col])

        # Basis from MethodSpecificationName
        if basis_col == 'MethodSpecificationName':
            
            # Add basis out column (i.e., 'Speciation') if it doesn't exist
            if self.col.basis not in self.df.columns:
                self.df[self.col.basis] = nan
            
            # Mask to characteristic
            self.df[c_mask] = basis.basis_from_methodSpec(self.df[c_mask])

            # Basis from unit
            try:
                basis_dict = basis.unit_basis_dict(self.out_col)
                self.df[c_mask] = basis.basis_from_unit(self.df[c_mask],
                                                        basis_dict,
                                                        self.col.unit_out)
            except KeyError:
                pass
            # Finish by filling any NAs with char_val based default
            col = self.col.basis

            # Get built-in char_val based on out_col attribute
            char_keys, char_vals = zip(*domains.out_col_lookup().items())
            char_val = list(char_keys)[list(char_vals).index(self.out_col)]

            self.df.loc[c_mask, col] = self.df.loc[c_mask, col].fillna(char_val)

            # Drop instances of 'as '
            self.df.loc[c_mask, col] = [bas[3:]
                                        if bas.startswith('as ') else bas
                                        for bas in self.df.loc[c_mask, col]]

        else:
            self.df[c_mask] = basis.update_result_basis(self.df[c_mask],
                                                        basis_col,
                                                        self.col.unit_out)

    def update_ureg(self):
        """Update class unit registry to define units based on out_col"""
        for definition in domains.registry_adds_list(self.out_col):
            self.ureg.define(definition)

    def update_units(self, units_out):
        """
        Update object units attribute to convert everything into. Does not do
        the conversion.
        
        Parameters
        ----------
        units_out : str
            Units to convert results into.

        Examples
        --------
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        >>> wq.units
        'mg/l'
        
        >>> wq.update_units('mg/kg')
        >>> wq.units
        'mg/kg'
        """
        self.units = units_out

    def measure_mask(self, column=None):
        """
        Get mask that is characteristic specific (c_mask) and only has valid
        col measures (Non-NA).
        
        Parameters
        ----------
        column : str, optional
            DataFrame column name to use. Default None uses self.out_col

        Examples
        --------
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        >>> wq.measure_mask()
        0     True
        1    False
        2     True
        dtype: bool
        """
        if column:
            return self.c_mask & self.df[column].notna()
        return self.c_mask & self.df[self.out_col].notna()

    def convert_units(self, default_unit=None, errors='raise'):
        """
        Update object DataFrame's out-col to convert from old units to
        default_unit.

        Parameters
        ----------
        default_unit : str, optional
            Units to convert values to. Default None uses units attribute.
        errors : str, optional
            Values of ‘ignore’, ‘raise’, or ‘skip’. The default is ‘raise’.
            If ‘raise’, invalid dimension conversions will raise an exception.
            If ‘skip’, invalid dimension conversions will not be converted.
            If ‘ignore’, invalid dimension conversions will be NaN.

        Examples
        --------
        Build dataframe to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Temperature, water',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/ml', 'deg C'],
        ...                 'ResultMeasureValue': ['1.0', '10.0',],
        ...                 })
        >>> df
           CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0          Phosphorus                         mg/ml                1.0
        1  Temperature, water                         deg C               10.0
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        
        >>> wq.convert_units()
        >>> wq.df
           CharacteristicName  ...                            Phosphorus
        0          Phosphorus  ...  1000.0000000000001 milligram / liter
        1  Temperature, water  ...                                   NaN
        """
        if default_unit:
            self.units = default_unit
        df_out = self.df
        m_mask = self.measure_mask()

        params = {'quantity_series': df_out.loc[m_mask, self.out_col],
                  'unit_series': df_out.loc[m_mask, self.col.unit_out],
                  'units': self.units,
                  'ureg': self.ureg,
                  'errors': errors}
        df_out.loc[m_mask, self.out_col] = harmonize.convert_unit_series(**params)
        self.df = df_out

    def apply_conversion(self, convert_fun, unit, u_mask=None):
        """
        Apply special dimension changing conversions using functions in convert
        module and applying them across all cases of current unit.

        Parameters
        ----------
        convert_fun : function
            Conversion function to apply.
        unit : str
            Current unit.
        u_mask : pandas.Series, optional
            Mask to use to identify what is being converted.
            The default is None, creating a unit mask based on unit.

        Examples
        --------
        Build dataframe to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Dissolved oxygen (DO)', 'Dissolved oxygen (DO)',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/l', '%'],
        ...                 'ResultMeasureValue': ['1.0', '10.0',],
        ...                 })
        >>> df
              CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0  Dissolved oxygen (DO)                          mg/l                1.0
        1  Dissolved oxygen (DO)                             %               10.0
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Dissolved oxygen (DO)')        
        >>> wq.apply_conversion(convert.DO_saturation, '%')
        >>> wq.df[['Units', 'DO']]
        """
        # TODO: QA flag inexact conversions?
        df_out = self.df
        if u_mask is None:
            u_mask = self._unit_mask(unit)
        unit = self.ureg.Quantity(unit)  # Pint quantity object from unit
        old_vals = df_out.loc[u_mask, self.out_col]
        try:
            new_quants = [convert_fun(x*unit) for x in old_vals]
        except ValueError:
            #print(old_vals.iloc[0]*unit)
            # string to avoid altered ureg issues
            new_quants = [convert_fun(str(x*unit)) for x in old_vals]
        # 1run=6505.62ms (may be slower) vs apply (5888.43ms)
        #new_vals = old_vals.apply(lambda x: convert_fun(x*unit).magnitude)
        new_vals = [quant.magnitude for quant in new_quants]
        df_out.loc[u_mask, self.out_col] = new_vals
        df_out.loc[u_mask, self.col.unit_out] = str(new_quants[0].units)
        # self.units <- was used previously, sus when units is not default

        self.df = df_out

    def dimensions_list(self, m_mask=None):
        """
        Use character object to retrieve list of unique dimensions.

        Parameters
        ----------
        m_mask : pandas.Series, optional
            Conditional mask to limit rows.
            The default None, uses measure_mask().

        Returns
        -------
        list
            List of units with mis-matched dimensions.

        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Phosphorus',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/l', 'mg/kg',],
        ...                 'ResultMeasureValue': ['1.0', '10',],      
        ...                 })
        >>> df
          CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0         Phosphorus                          mg/l                1.0
        1         Phosphorus                         mg/kg                 10
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        
        >>> wq.dimensions_list()
        'mg/kg'
        """
        if m_mask is None:
            m_mask = self.measure_mask()
        return harmonize.units_dimension(self.df.loc[m_mask,
                                                     self.col.unit_out],
                                         self.units,
                                         self.ureg)

    def replace_unit_str(self, old, new, mask=None):
        """
        Simple way to replace ALL instances of old str with new str in units.

        Parameters
        ----------
        old : str
            sub-string to find and replace
        new : str
            sub-string to replace old sub-string
        mask : pandas.Series, optional
            Conditional mask to limit rows.
            The default None, uses the c_mask attribute.
            
        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Temperature, water', 'Temperature, water',],
        ...                 'ResultMeasure/MeasureUnitCode': ['deg C', 'deg F',],
        ...                 'ResultMeasureValue': ['31', '87',],      
        ...                 })
        >>> df
           CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0  Temperature, water                         deg C                 31
        1  Temperature, water                         deg F                 87
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Temperature, water')
        >>> wq.df
           CharacteristicName ResultMeasure/MeasureUnitCode  ...  Units Temperature
        0  Temperature, water                         deg C  ...  deg C          31
        1  Temperature, water                         deg F  ...  deg F          87
         
        >>> wq.replace_unit_str(' ', '')
        >>> wq.df
           CharacteristicName ResultMeasure/MeasureUnitCode  ... Units Temperature
        0  Temperature, water                         deg C  ...  degC          31
        1  Temperature, water                         deg F  ...  degF          87
        """
        df_out = self.df
        if mask is None:
            mask = self.c_mask
        unit_col = self.col.unit_out
        df_out.loc[mask, unit_col] = df_out.loc[mask, unit_col].str.replace(old, new)
        self.df = df_out

    def replace_unit_by_dict(self, val_dict, mask=None):
        """
        A simple way to do multiple replace_in_col() replacements of val_dict
        key with val_dict value.

        Parameters
        ----------
        val_dict : dict
            Occurrences of key in the unit column are replaced with the value.
        mask : pandas.Series, optional
            Conditional mask to limit rows.
            The default None, uses the c_mask attribute.

        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Fecal Coliform', 'Fecal Coliform',],
        ...                 'ResultMeasure/MeasureUnitCode': ['#/100ml', 'MPN',],
        ...                 'ResultMeasureValue': ['1.0', '10',],      
        ...                 })
        >>> df
          CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0     Fecal Coliform                       #/100ml                1.0
        1     Fecal Coliform                           MPN                 10
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Fecal Coliform')
        >>> wq.df
          CharacteristicName ResultMeasure/MeasureUnitCode  ...    Units Fecal_Coliform
        0     Fecal Coliform                       #/100ml  ...  #/100ml            1.0
        1     Fecal Coliform                           MPN  ...      MPN           10.0
        
        [2 rows x 5 columns]
         
        >>> wq.replace_unit_by_dict(domains.UNITS_REPLACE['Fecal_Coliform'])
        >>> wq.df
          CharacteristicName ResultMeasure/MeasureUnitCode  ...        Units Fecal_Coliform
        0     Fecal Coliform                       #/100ml  ...  CFU/(100ml)            1.0
        1     Fecal Coliform                           MPN  ...  MPN/(100ml)           10.0
        """
        col = self.col.unit_out
        for item in val_dict.items():
            self._replace_in_col(col, item[0], item[1], mask)

    def fraction(self, frac_dict=None, suffix=None,
                 fract_col='ResultSampleFractionText'):
        """
        Create columns for sample fractions, use frac_dict to set their names.

        Parameters
        ----------
        frac_dict : dict, optional
            Dictionary where {fraction_name : new_col}.
            The default None starts with an empty dictionary.
        suffix : str, optional
            String to add to the end of any new column name.
            The default None, uses out_col attribute.
        fract_col : str, optional
            Column name where sample fraction is defined.
            The default is 'ResultSampleFractionText'.

        Returns
        -------
        frac_dict : dict
            frac_dict updated to include any frac_col not already defined.
            
        Examples
        --------
        
        Not fully implemented with TADA table yet
        """
        c_mask = self.c_mask
        if suffix is None:
            suffix = self.out_col

        catch_all = 'Other_{}'.format(suffix)
        if frac_dict is None:
            frac_dict = {catch_all: ''}
        else:
            if catch_all not in frac_dict.keys():
                frac_dict[catch_all] = ['']
        if not isinstance(frac_dict[catch_all], list):
            frac_dict[catch_all] = [frac_dict[catch_all]]

        # Get all domain values
        #accepted_fracs = list(domains.get_domain_dict('ResultSampleFraction').keys())
        for key in domains.get_domain_dict('ResultSampleFraction').keys():
            # Check against expected fractions and add others to catch_all
            if key not in [x for v in frac_dict.values() for x in v]:
                frac_dict[catch_all] += [key]
        # Flatten for some uses
        samp_fract_set = sorted({x for v in frac_dict.values() for x in v})

        # Check for sample fraction column
        harmonize.df_checks(self.df, [fract_col])
        # Replace bad sample fraction w/ nan
        self.df = self._replace_in_col(fract_col, ' ', nan, c_mask)

        df_out = self.df  # Set var for easier referencing

        # Clean up sample fraction column based on charName
        # Get char
        c_dict = domains.out_col_lookup()
        char = list(c_dict.keys())[list(c_dict.values()).index(self.out_col)]
        # Get dictionary for updates from TADA
        harmonize_dict = domains.harmonize_TADA_dict()
        # TADA keys are all caps
        harmonize_fract = harmonize_dict[char.upper()]
        # Loop through dictionary making updates to sample fraction
        for fract_set in harmonize_fract.values():
            for row in fract_set.items():            
                fract_mask = df_out[c_mask][fract_col].isin(row[1])  # Mask by values
                df_out[c_mask][fract_mask][fract_col] = row[0]  # Update to key
        # Compare df_out againt self.df to add QA flag if changed
        cond_change = ~(df_out[fract_col] == self.df[fract_col])
        cond_na = df_out[fract_col].notna()
        df_out[cond_change & cond_na]
        # TODO: LEFT OFF ABOVE IS STILL EMPTY

        self.df = df_out
        
        # Make column for any unexpected Sample Fraction values, loudly
        for s_f in set(df_out[c_mask][fract_col].dropna()):
            if s_f not in samp_fract_set:
                char = '{}_{}'.format(s_f.replace(' ', '_'), suffix)
                frac_dict[char] = s_f
                prob = '"{}" column for {}, may be error'.format(char, s_f)
                warn('Warning: ' + prob)
                # TODO: add QA_flag
        # Test we didn't skip any SampleFraction
        samp_fract_set = sorted({x for v in frac_dict.values() for x in v})
        for s_f in set(df_out[c_mask][fract_col].dropna()):
            assert s_f in samp_fract_set, '{} check in {}'.format(s_f,
                                                                      fract_col)
        # Create out columns for each sample fraction
        for frac in frac_dict.items():
            col = frac[0]  # New column name
            for smp_frac in frac[1]:
                if smp_frac in set(df_out.loc[c_mask, fract_col].dropna()):
                    # New subset mask for sample frac
                    f_mask = c_mask & (df_out[fract_col]==smp_frac)
                    # Copy measure to new col (new col name from char_list)
                    df_out.loc[f_mask, col] = df_out.loc[f_mask, suffix]
                elif smp_frac == '':
                    # Values where sample fraction missing go to catch all
                    if df_out.loc[c_mask, fract_col].isnull().values.any():
                        # New subset mask
                        f_mask = c_mask & (df_out[fract_col].isnull())
                        # Copy measure to new col
                        df_out.loc[f_mask, col] = df_out.loc[f_mask, suffix]
        self.df = df_out

        return frac_dict

    def dimension_fixes(self):
        """
        Input/output for dimension handling.

        Note: this is done one dimension at a time, except for mole
        conversions which are further divided by basis (one at a time)

        Returns
        -------
        dimension_dict : dict
            Dictionary with old_unit:new_unit.
        mol_list : list
            List of Mole (substance) units.

        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Phosphorus', 'Phosphorus',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/l', 'mg/kg',],
        ...                 'ResultMeasureValue': ['1.0', '10',],      
        ...                 })
        >>> df
          CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0         Phosphorus                          mg/l                1.0
        1         Phosphorus                         mg/kg                 10

        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Phosphorus')
        
        >>> wq.dimension_fixes()
        ({'mg/kg': 'mg/kg * H2O'}, [])
        """
        dimension_dict = {}  # Empty dict to update to
        mol_list = []  # Empty list to append to

        # If converting to/from moles has extra steps
        if self.ureg(self.units).check({'[substance]': 1}):
            # Convert everything to MOLES!!!
            # Must consider the different speciation for each
            #TODO: This could be problematic given umol/l
            warn('This feature is not available yet')
            return {}, []
        for unit in self.dimensions_list():
            if self.ureg(unit).check({'[substance]': 1}):
                mol_params = {'ureg': self.ureg,
                              'Q_': self.ureg.Quantity(1, unit),}
                # Moles need to be further split by basis
                basis_lst = list(set(self.df.loc[self.c_mask, self.col.basis]))
                for speciation in basis_lst:
                    mol_params['basis'] = speciation
                    quant = str(convert.moles_to_mass(**mol_params))
                    dim_tup = self._dimension_handling(unit,
                                                       quant,
                                                       self.ureg)
                    dimension_dict.update(dim_tup[0])
                    mol_list+= dim_tup[1]
            else:
                dim_tup = self._dimension_handling(unit,
                                                   ureg = self.ureg)
                dimension_dict.update(dim_tup[0])
        return dimension_dict, mol_list

    def moles_convert(self, mol_list):
        """
        Update out_col with moles converted and reduce unit_col to units

        Parameters
        ----------
        mol_list : list
            List of Mole (substance) units.

        Examples
        --------
        Build DataFrame to use as input:
        
        >>> from pandas import DataFrame
        >>> df = DataFrame({'CharacteristicName': ['Carbon', 'Carbon',],
        ...                 'ResultMeasure/MeasureUnitCode': ['mg/l', 'umol',],
        ...                 'ResultMeasureValue': ['1.0', '0.265',],      
        ...                 })
        >>> df
          CharacteristicName ResultMeasure/MeasureUnitCode ResultMeasureValue
        0             Carbon                          mg/l                1.0
        1             Carbon                          umol              0.265
        
        Build WQ Characteristic Data object from DataFrame:
            
        >>> wq = harmonize.WQCharData(df, 'Organic carbon')
        >>> wq.df
          CharacteristicName ResultMeasure/MeasureUnitCode  ... Units Carbon
        0             Carbon                          mg/l  ...  mg/l    1.0
        1             Carbon                          umol  ...  umol  0.265
    
        [2 rows x 5 columns]
        
        Assemble moles list:

        >>> dimension_dict, mol_list = wq.dimension_fixes()
        >>> mol_list
        ['umol']
        
        >>> wq.moles_convert(mol_list)
        >>> wq.df
          CharacteristicName ResultMeasure/MeasureUnitCode  ... Units     Carbon
        0             Carbon                          mg/l  ...  mg/l        1.0
        1             Carbon                          umol  ...  mg/l  0.0477424
        """
        # Variables from WQP
        df_out = self.df
        unit_col = self.col.unit_out
        ureg = self.ureg
        out_col = self.out_col

        for quant in mol_list:
            mol_mask = self._unit_mask(quant)
            df_out.loc[mol_mask, out_col] = ureg.Quantity(quant) * df_out[out_col]
            df_out.loc[mol_mask, unit_col] = str(ureg.Quantity(quant).units)

        self.df = df_out
        self.ureg = ureg
