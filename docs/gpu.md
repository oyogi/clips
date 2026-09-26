# GPU support

Video encoding and face detection use separate interfaces:

- **Encoding:** FFmpeg probes a real H.264 VA-API encode, then falls back to a CPU
  encoder if necessary. The terminal shows the selected encoder.
- **Face detection:** OpenCV YuNet can use OpenCL or a CUDA-enabled OpenCV build.
  Available GPU backends are warmed up and timed against the CPU on the first
  sampled frame. A GPU is selected only when it is at least 10% faster and produces
  comparable detections. The chosen backend appears in progress and export details.

Run `youtube-clips doctor` or `python clips.py doctor` to check both. The diagnostic
uses a synthetic frame; selection during a real export uses that video's frame.
Inference timings exclude video decoding, resizing, rendering and model startup.
Small models and short clips can be faster on the CPU despite a working GPU.

For example, an Intel Iris Xe with Intel OpenCL 26.22 took about **3.6–3.8 ms** on
CPU and **6.6–6.9 ms** with OpenCL on sampled images. The app correctly kept face
detection on CPU while using the GPU for video encoding. Installing OpenCL makes
GPU detection available; it does not guarantee a speedup.

The dependency is limited to OpenCV 4.13: the 4.14 wheel produced an OpenCL kernel
compilation error on this Intel driver. The same images ran successfully on 4.13
and produced matching detections. `uv run` picks up the compatible version;
with pip, reinstall the project to update its dependencies.

On Fedora with Intel graphics, the media driver used by FFmpeg does not provide
OpenCL. Install the separate compute runtime if you want to try GPU detection:

```bash
sudo dnf install intel-opencl ocl-icd
```

Then start a new app process and run the diagnostic again. The standard OpenCV
wheel supports OpenCL, but does not include CUDA. NVIDIA CUDA use needs an OpenCV
build compiled with its CUDA DNN backend. No extra Python inference framework is
required by this project.

The app samples faces about 2.5 times per second and interpolates crop motion.
GPU inference cannot remove the cost of decoding the source or composing frames.
Detection finds visible faces, not identities or the active speaker.

References: [OpenCV FaceDetectorYN](https://docs.opencv.org/doc/doxygen/html/df/d20/classcv_1_1FaceDetectorYN.html),
[OpenCV DNN targets](https://docs.opencv.org/doc/doxygen/html/d6/d0f/group__dnn.html),
[Fedora Intel OpenCL](https://packages.fedoraproject.org/pkgs/intel-compute-runtime/intel-opencl/).
