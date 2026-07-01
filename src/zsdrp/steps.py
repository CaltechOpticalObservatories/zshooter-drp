import numpy as np
from pyreduce.reduce import combine_calibrate
from pyreduce.trace import trace
from pyreduce.extract import extract_normalize, extract
from pyreduce.spectra import ExtractionParams, Spectra


def trace_wrapper(image, step_cfg, debug_dir=None, order_centers=None, **kwargs):
    mapping = {'split_sigma': 'sigma'}
    params = {mapping.get(k,k): v for k, v in step_cfg.items()}

    params.pop('bias_scaling') if 'bias_scaling' in params else None
    params.pop('norm_scaling') if 'norm_scaling' in params else None
    params['order_centers'] = order_centers
    params['debug_dir'] = debug_dir

    return trace(image, **params)

def normflat_wrapper(image, header, traces, step_cfg, **kwargs):
    mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
               'extraction_reject': 'reject_threshold'}
    params = {mapping.get(k,k): v for k, v in step_cfg.items()}
    params['reject_threshold'] = params.get('reject_threshold', 6)
    params.update({'gain': header["e_gain"], 'readnoise': header["e_readn"], 'dark': header["e_drk"]})
    params['scatter'] = kwargs.get('scatter', None)

    norm, _, blaze, slitfunc, column_range = extract_normalize(image, traces, **params)

    blaze = np.ma.filled(blaze, 0)
    norm = np.ma.filled(norm, 1)
    norm = np.nan_to_num(norm, nan=1)

    # Metadata for slitfunc
    n_traces = len(traces)
    slitfunc_meta = {
        "extraction_height": params["extraction_height"],
        "osample": params["osample"],
        "trace_range": (0, n_traces),
        "n_traces_selected": n_traces,
    }
    return norm, blaze, slitfunc, slitfunc_meta

def science_wrapper(images, instrument, channel, bias, bhead,
                    norm, order_centers, trace_step_cfg, sci_step_cfg,
                    **kwargs):
    """
    Preproc science images (combine_calibrate), run tracing, then run extraction.
    :param images: list of science images that belong to same target
    :param instrument: Instrument instance
    :param channel: Channel name
    :param bias: Bias image
    :param bhead: Bias header
    :param norm: Norm image
    :param order_centers: Order centers from tracing the flat image
    :param trace_step_cfg: Step configuration for science tracing
    :param sci_step_cfg: Step configuration for science extraction
    """
    mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
               'extraction_reject': 'reject_threshold', 'extraction_method':'extraction_type'}
    params = {mapping.get(k,k): v for k,v in sci_step_cfg.items()}


    im, head = combine_calibrate(images, instrument=instrument, channel=channel, bias=bias, bhead=bhead, norm=norm,
                                 extraction_height=params['extraction_height'], bias_scaling=params.pop('bias_scaling'),
                                 norm_scaling=params.pop('norm_scaling'))
    traces = trace_wrapper(im, trace_step_cfg, order_centers=order_centers)
    params.update({'gain': head["e_gain"], 'readnoise': head["e_readn"], 'dark': head["e_drk"]})
    params['scatter'] = kwargs.get('scatter', None)

    meta = ExtractionParams(
        osample=params.get("oversampling", 10),
        lambda_sf=params.get("smooth_slitfunction", 1.0),
        lambda_sp=params.get("smooth_spectrum", 0.0),
        swath_width=params.get("swath_width"),
    )
    spec = extract(im, traces, **params)
    spec_obj = Spectra(header=head, data=spec, params=meta)

    return spec_obj

