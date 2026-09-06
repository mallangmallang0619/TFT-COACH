"""CPU inference settings for the low-frequency live capture pipeline."""


def cpu_session_options():
    # Keep ONNX optional: callers already handle missing runtime/model files.
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # Capture runs at 2 FPS. Sleeping workers avoid burning CPU between reads.
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return options
