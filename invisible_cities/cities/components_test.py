import os

import numpy as np
import tables as tb
import pandas as pd

from argparse  import Namespace
from functools import partial

from pytest import mark
from pytest import raises
from pytest import warns

from .. core.configure     import EventRange as ER
from .. core.exceptions    import InvalidInputFileStructure
from .. core.testing_utils import    assert_tables_equality
from .. core               import system_of_units as units

from .  components import event_range
from .  components import collect
from .  components import copy_mc_info
from .  components import WfType
from .  components import wf_from_files
from .  components import pmap_from_files
from .  components import compute_xy_position
from .  components import city
from .  components import hits_and_kdst_from_files
from .  components import mcsensors_from_file
from .  components import create_timestamp

from .. dataflow   import dataflow as fl


def _create_dummy_conf_with_event_range(value):
    return Namespace(event_range = value)


@mark.parametrize("given expected".split(),
                  ((       9          , (   9,     )),
                   ( (     9,        ), (   9,     )),
                   ( (     5,       9), (   5,    9)),
                   ( (     5, ER.last), (   5, None)),
                   (  ER.all          , (None,     )),
                   ( (ER.all,        ), (None,     ))))
def test_event_range_valid_options(given, expected):
    conf = _create_dummy_conf_with_event_range(given)
    assert event_range(conf) == expected


@mark.parametrize("given",
                  ( ER.last    ,
                   (ER.last,)  ,
                   (ER.last, 4),
                   (ER.all , 4),
                   ( 1,  2,  3)))

def test_event_range_invalid_options_raises_ValueError(given):
    conf = _create_dummy_conf_with_event_range(given)
    with raises(ValueError):
        event_range(conf)


_rwf_from_files = partial(wf_from_files, wf_type=WfType.rwf)
@mark.parametrize("source filename".split(),
                  ((_rwf_from_files, "defective_rwf_rd_pmtrwf.h5"      ),
                   (_rwf_from_files, "defective_rwf_rd_sipmrwf.h5"     ),
                   (_rwf_from_files, "defective_rwf_run_events.h5"     ),
                   (_rwf_from_files, "defective_rwf_trigger_events.h5" ),
                   (_rwf_from_files, "defective_rwf_trigger_trigger.h5"),
                   (pmap_from_files, "defective_pmp_pmap_all.h5"       ),
                   (pmap_from_files, "defective_pmp_run_events.h5"     )))
def test_sources_invalid_input_raises_InvalidInputFileStructure(ICDATADIR, source, filename):
    full_filename = os.path.join(ICDATADIR, "defective_files", filename)
    s = source((full_filename,))
    with raises(InvalidInputFileStructure):
        next(s)


def test_compute_xy_position_depends_on_actual_run_number():
    """
    The channels entering the reco algorithm are the ones in a square of 3x3
    that includes the masked channel.
    Scheme of SiPM positions (the numbers are the SiPM charges):
    x - - - >
    y | 5 5 5
      | X 7 5
      v 5 5 5

    This test is meant to fail if them compute_xy_position function
    doesn't use the run_number parameter.
    """
    minimum_seed_charge = 6*units.pes
    reco_parameters = {'Qthr': 2*units.pes,
                       'Qlm': minimum_seed_charge,
                       'lm_radius': 0*units.mm,
                       'new_lm_radius': 15 * units.mm,
                       'msipm': 9,
                       'consider_masked': True}
    run_number = 6977
    find_xy_pos = compute_xy_position('new', run_number, **reco_parameters)

    xs_to_test  = np.array([-65, -65, -55, -55, -55, -45, -45, -45])
    ys_to_test  = np.array([  5,  25,   5,  15,  25,   5,  15,  25])
    xys_to_test = np.stack((xs_to_test, ys_to_test), axis=1)

    charge         = minimum_seed_charge - 1
    seed_charge    = minimum_seed_charge + 1
    charge_to_test = np.array([charge, charge, charge, seed_charge, charge, charge, charge, charge])

    find_xy_pos(xys_to_test, charge_to_test)



def test_city_adds_default_detector_db(config_tmpdir):
    default_detector_db = 'new'
    args = {'files_in'    : 'dummy_in',
            'file_out'    : os.path.join(config_tmpdir, 'dummy_out')}
    @city
    def dummy_city(files_in, file_out, event_range, detector_db):
        with tb.open_file(file_out, 'w'):
            pass
        return detector_db

    db = dummy_city(**args)
    assert db == default_detector_db


def test_city_does_not_overwrite_detector_db(config_tmpdir):
    args = {'detector_db' : 'some_detector',
            'files_in'    : 'dummy_in',
            'file_out'    : os.path.join(config_tmpdir, 'dummy_out')}
    @city
    def dummy_city(files_in, file_out, event_range, detector_db):
        with tb.open_file(file_out, 'w'):
            pass
        return detector_db

    db = dummy_city(**args)
    assert db == args['detector_db']


def test_city_only_pass_default_detector_db_when_expected(config_tmpdir):
    args = {'files_in'    : 'dummy_in',
            'file_out'    : os.path.join(config_tmpdir, 'dummy_out')}
    @city
    def dummy_city(files_in, file_out, event_range):
        with tb.open_file(file_out, 'w'):
            pass

    dummy_city(**args)

def test_hits_and_kdst_from_files(ICDATADIR):
    event_number = 1
    timestamp    = 0.
    num_hits     = 13
    keys = ['hits', 'kdst', 'run_number', 'event_number', 'timestamp']
    file_in     = os.path.join(ICDATADIR    ,  'Kr83_nexus_v5_03_00_ACTIVE_7bar_3evts.HDST.h5')
    generator = hits_and_kdst_from_files([file_in])
    output = next(generator)
    assert set(keys) == set(output.keys())
    assert output['event_number']   == event_number
    assert output['timestamp']      == timestamp
    assert len(output['hits'].hits) == num_hits
    assert type(output['kdst'])     == pd.DataFrame


def test_collect():
    the_source    = list(range(0,10))
    the_collector = collect()
    the_result    = fl.push(source = the_source,
                            pipe   = fl.pipe(the_collector.sink),
                            result = the_collector.future)
    assert the_source == the_result


def test_copy_mc_info_noMC(ICDATADIR, config_tmpdir):
    file_in  = os.path.join(ICDATADIR, 'run_2983.h5')
    file_out = os.path.join(config_tmpdir, 'dummy_out.h5')
    with tb.open_file(file_out, "w") as h5out:
        with warns(UserWarning):
            copy_mc_info([file_in], h5out, [], 'new', -6400)


@mark.xfail
def test_copy_mc_info_repeated_event_numbers(ICDATADIR, config_tmpdir):
    file_in  = os.path.join(ICDATADIR, "Kr83_nexus_v5_03_00_ACTIVE_7bar_10evts.sim.h5")
    file_out = os.path.join(config_tmpdir, "dummy_out.h5")

    with tb.open_file(file_out, 'w') as h5out:
        copy_mc_info([file_in, file_in], h5out, [0,1,0,9])
        events_in_h5out = h5out.root.MC.extents.cols.evt_number[:]
        assert events_in_h5out.tolist() == [0,1,0,9]


def test_copy_mc_info_split_nexus_events(ICDATADIR, config_tmpdir):
    file_in  = os.path.join(ICDATADIR                                       ,
                            "nexus_new_kr83m_full.newformat.splitbuffers.h5")
    file_out = os.path.join(config_tmpdir, "dummy_out.h5")

    with tb.open_file(file_out, 'w') as h5out:
        copy_mc_info([file_in], h5out, [0, 10, 11], 'new', -6400)

    tables = ("MC/hits"        , "MC/particles", "MC/sns_positions",
              "MC/sns_response", "Run/eventMap")
    with tb.open_file(file_in) as h5in, tb.open_file(file_out) as h5out:
        for table in tables:
            assert hasattr(h5out.root, table)
            got      = getattr(h5out.root, table)
            expected = getattr(h5in .root, table)
            assert_tables_equality(got, expected)



def test_mcsensors_from_file_fast_returns_empty(ICDATADIR):
    rate = 0.5
    file_in = os.path.join(ICDATADIR, "nexus_new_kr83m_fast.newformat.sim.h5")
    sns_gen = mcsensors_from_file([file_in], 'new', -7951, rate)
    with warns(UserWarning, match='No binning info available.'):
        first_evt = next(sns_gen)
    assert first_evt[ 'pmt_resp'].empty
    assert first_evt['sipm_resp'].empty


def test_mcsensors_from_file_correct_yield(ICDATADIR):
    evt_no         =    0
    rate           =    0.5
    npmts_hit      =   12
    total_pmthits  = 4303
    nsipms_hit     =  313
    total_sipmhits =  389
    keys           = ['event_number', 'timestamp', 'pmt_resp' , 'sipm_resp']

    file_in   = os.path.join(ICDATADIR, "nexus_new_kr83m_full.newformat.sim.h5")
    sns_gen   = mcsensors_from_file([file_in], 'new', -7951, rate)
    first_evt = next(sns_gen)

    assert set(keys) == set(first_evt.keys())

    assert      first_evt['event_number']                 == evt_no
    assert      first_evt[   'timestamp']                 >= evt_no / rate
    assert type(first_evt[    'pmt_resp'])                == pd.DataFrame
    assert type(first_evt[   'sipm_resp'])                == pd.DataFrame
    assert  len(first_evt[    'pmt_resp'].index.unique()) == npmts_hit
    assert      first_evt[    'pmt_resp'].shape[0]        == total_pmthits
    assert  len(first_evt[   'sipm_resp'].index.unique()) == nsipms_hit
    assert      first_evt[   'sipm_resp'].shape[0]        == total_sipmhits


def test_create_timestamp_greater_with_greater_eventnumber():
    """
    Value of timestamp must be always positive and 
    greater with greater event numbers.
    """

    rate_1   =   0.5
    rate_2   =   0.6
    evt_no_1 =  10.
    evt_no_2 = 100.

    timestamp_1 = create_timestamp(rate_1)
    timestamp_2 = create_timestamp(rate_2)

    assert     timestamp_1(evt_no_1)  <  timestamp_2(evt_no_2)


@mark.filterwarnings("ignore:Zero rate"    )
@mark.filterwarnings("ignore:Negative rate")
def test_create_timestamp_physical_rate():
    """
    Check the rate is always physical.
    """

    rate_1   =   0.   * units.hertz
    rate_2   = - 0.42 * units.hertz
    evt_no_1 =  11.
    evt_no_2 = 111.

    timestamp_1 = create_timestamp(rate_1)
    timestamp_2 = create_timestamp(rate_2)

    assert timestamp_1(evt_no_1) >= 0
    assert timestamp_2(evt_no_2) >= 0

