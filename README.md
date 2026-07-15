<h1><img width="64px" src="ai_diffusion/icons/logo-128.png"> Generative AI <i>for Krita</i> — UX Edition</h1>

A usability-focused fork of the [Krita AI Diffusion plugin](https://github.com/Acly/krita-ai-diffusion)
with numerous quality-of-life improvements for prompt handling, LoRA management
and batch generation workflows.

All credit for the plugin itself goes to [Acly](https://github.com/Acly) and the
upstream contributors — this fork only layers UX improvements on top and tracks
upstream releases (currently based on v1.52.1).

**This fork is for you if:**

* you work with large LoRA collections and want to browse them visually
  (previews, tags, favorites) instead of memorizing file names
* you generate batches and want systematic control over which prompt/LoRA
  combination each batch item uses
* you want prompt history actions, batch sizing and image export to be less
  clicky and more predictable

## What's different from upstream

### Sequential wildcards & batch control
* **Sequential wildcard syntax `[[a|b|c]]`**: unlike the random `{a|b|c}` syntax,
  options are consumed in order across a batch — batch item 1 gets `a`, item 2
  gets `b`, and so on. Multiple `[[...]]` groups form a **Cartesian product**
  (`[[black|white]] [[cat|dog]]` generates all 4 combinations).
* **LoRAs inside wildcards**: `<lora:...>` tags inside `[[...]]` groups are
  correctly switched per batch item — each image is generated with its own LoRA
  set, not just the first one.
* **Batch count up to 1000** (upstream: 10) with an editable spinbox, plus a
  one-click button that sets the batch count to the number of sequential
  wildcard combinations in the prompt.
* **Loop Generate**: toggle button next to Generate keeps enqueuing new
  batches automatically as soon as the queue drains, until toggled off —
  useful for unattended overnight generation. Auto-disables on errors.

### LoRA Browser
A visual LoRA picker (funnel icon in the prompt field) integrated with
[ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager):

* preview images (lazy-loaded), name search, tag filter, base-model filter,
  favorites filter, adjustable thumbnail size
* trigger words fetched from CivitAI metadata, insertable together with the
  LoRA tag (per phrase group or all)
* **multi-select**: pick several LoRAs and insert them as a random `{a|b}` or
  sequential `[[a|b]]` wildcard group in one click, with per-LoRA trigger words
* non-modal window (Krita stays interactive), disk-cached LoRA list for
  instant reopening
* falls back to a plain file list if Lora Manager is not installed

### Style Picker
Style/checkpoint selection was an unmanageable dropdown once you have
hundreds of presets. Replaced with a searchable, non-modal picker dialog
(same design language as the LoRA browser):

* live search by name/checkpoint, filter by base-model family
* **base model family detection**: Illustrious and Pony checkpoints are
  architecturally identical to SDXL, so they can't be told apart from the
  model weights — a new per-style "Base Model Family" field defaults to a
  filename-based guess (like the LoRA browser) but is manually overridable
  from a dropdown, and drives the picker's filter
* favorite styles (right-click or `F`), pinned in their own section above
  the existing "Recently Used" list

### Faster startup
* **Model list disk cache**: the 700+ model discovery calls at startup are
  cached per server; use the Refresh button to update after installing models.

### History & export
* **Split prompt actions**: "Apply Prompt to Field" and "Copy Prompt to
  Clipboard" are separate context menu entries (upstream does both at once),
  each available in raw and evaluated form.
* **Search & filter the generation history**: search box filters by prompt
  text live; two toggles show only favorited or only canvas-applied images.
* **Favorite images**: mark generated results as favorites (right-click or
  `F` hotkey), persisted across restarts, shown as a star badge on the
  thumbnail.
* **Save to Eagle**: send generated images straight to the
  [Eagle](https://eagle.cool) library via its local API — with the prompt as
  title, full generation metadata as annotation, and style/LoRA names as tags.

### Custom workflows
Ready-made Krita-adapted workflows in [`custom_workflows/`](custom_workflows/)
for the [Krea 2 Identity Edit](https://huggingface.co/conradlocke/krea2-identity-edit)
model (requires the [comfyui-krea2edit](https://github.com/lbouaraba/comfyui-krea2edit)
node pack):

* **Krea2 Identity Edit** — single reference, the canvas is the edit source
* **Krea2 Identity Edit (Character + Scene)** — canvas is the scene, a
  selectable Krita layer provides the person reference
* both expose prompt, grounding_px and two stackable LoRA slots (dropdown with
  all server LoRAs) as Krita parameters

Copy them to `%APPDATA%\krita\ai_diffusion\workflows\` to use.

### Fixes
* Refresh Models button now actually updates the "missing models" display
  (upstream bug: stale warning until full reconnect)
* no crash when running custom workflow graphs without a style node

## Installation

Same as upstream — see the [Plugin Installation Guide](https://docs.interstice.cloud/installation).
To use this fork instead of the official release, clone this repository and
link/copy the `ai_diffusion` folder into Krita's `pykrita` directory
(the bundled `websockets` library must be added from an official release
package, it is not part of the repository).

Some features require additional software:
* LoRA Browser metadata: [ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)
* Save to Eagle: [Eagle](https://eagle.cool) running locally
* Krea2 workflows: [comfyui-krea2edit](https://github.com/lbouaraba/comfyui-krea2edit) nodes

---

# Original plugin documentation

✨[Features](#features) | ⚡ [Download](https://github.com/Acly/krita-ai-diffusion/releases/latest) | 🛠️[Installation](https://docs.interstice.cloud/installation) | 🎞️ [Video](https://youtu.be/Ly6USRwTHe0) | 🖼️[Gallery](#gallery) | 📖[User Guide](https://docs.interstice.cloud) | 💬[Discussion](https://github.com/Acly/krita-ai-diffusion/discussions) | 🗣️[Discord](https://discord.gg/pWyzHfHHhU)

This is a plugin to use generative AI in image painting and editing workflows
from within Krita. Visit
[**www.interstice.cloud**](https://www.interstice.cloud) for an introduction. Learn how to install and use it on [**docs.interstice.cloud**](https://docs.interstice.cloud).

The main goals of this project are:
* **Precision and Control.** Creating entire images from text can be unpredictable.
  To get the result you envision, you can restrict generation to selections,
  refine existing content with a variable degree of strength, focus text on image
  regions, and guide generation with reference images, sketches, line art,
  depth maps, and more.
* **Workflow Integration.** Most image generation tools focus heavily on AI parameters.
  This project aims to be an unobtrusive tool that integrates and synergizes
  with image editing workflows in Krita. Draw, paint, edit and generate seamlessly without worrying about resolution and technical details.
* **Local, Open, Free.** We are committed to open source models. Customize presets, bring your
  own models, and run everything local on your hardware. Cloud generation is also available
  to get started quickly without heavy investment.  

[![Watch video demo](media/screenshot-video-preview.webp)](https://youtu.be/Ly6USRwTHe0 "Watch video demo")

## <a name="features"></a> Features

* **Inpainting**: Use selections for generative fill, expand, to add or remove objects
* **Live Painting**: Let AI interpret your canvas in real time for immediate feedback. [Watch Video](https://youtu.be/AF2VyqSApjA?si=Ve5uQJWcNOATtABU)
* **Upscaling**: Upscale and enrich images to 4k, 8k and beyond without running out of memory.
* **Diffusion Models**: Flux 2, Z-Image, Stable Diffusion 1.5, XL, Illustrious
* **Edit Models**: Make modifications to images via text instructions
* **ControlNet**: Scribble, Line art, Canny edge, Pose, Depth, Normals, Segmentation, +more
* **IP-Adapter**: Reference images, Style and composition transfer, Face swap
* **Regions**: Assign individual text descriptions to image areas defined by layers.
* **Job Queue**: Queue and cancel generation jobs while working on your image.
* **History**: Preview results and browse previous generations and prompts at any time.
* **Strong Defaults**: Versatile default style presets allow for a streamlined UI.
* **Customization**: Create your own presets - custom checkpoints, LoRA, samplers and more.

## <a name="installation"></a> Getting Started

See the [Plugin Installation Guide](https://docs.interstice.cloud/installation) for instructions.

A concise (more technical) version is below:

### Operating System

Windows, Linux, MacOS

#### Hardware support

To run locally a powerful graphics card with at least 6 GB VRAM (NVIDIA) is
recommended. Otherwise generating images will take very long or may fail due to
insufficient memory!

<table>
<tr><td>NVIDIA GPU</td><td>supported via CUDA (Windows/Linux)</td></tr>
<tr><td>AMD GPU</td><td>supported via ROCm (Windows/Linux)</td></tr>
<tr><td>Intel GPU</td><td>supported via XPU (Windows/Linux)</td></tr>
<tr><td>Apple Silicon</td><td>MPS on macOS 14+</td></tr>
<tr><td>CPU</td><td>supported, but very slow</td></tr>
</table>


### Installation

1. If you haven't yet, go and install [Krita](https://krita.org/)! _Required version: 5.2.0 or newer_
1. [Download the plugin](https://github.com/Acly/krita-ai-diffusion/releases/latest).
2. Start Krita and install the plugin via Tools ▸ Scripts ▸ Import Python Plugin from File...
    * Point it to the ZIP archive you downloaded in the previous step.
    * Check [Krita's official documentation](https://docs.krita.org/en/user_manual/python_scripting/install_custom_python_plugin.html) for more options.
3. Restart Krita and create a new document or open an existing image.
4. To show the plugin docker: Settings ‣ Dockers ‣ AI Image Generation.
5. In the plugin docker, click "Configure" to start local server installation or connect.

> [!NOTE]
> If you encounter problems please check the [FAQ / list of common issues](https://docs.interstice.cloud/common-issues) for solutions.
>
> Reach out via [discussions](https://github.com/Acly/krita-ai-diffusion/discussions), our [Discord](https://discord.gg/pWyzHfHHhU), or report [an issue here](https://github.com/Acly/krita-ai-diffusion/issues). Please note that official Krita channels are **not** the right place to seek help with
> issues related to this extension!

### _Optional:_ Custom ComfyUI Server

The plugin uses [ComfyUI](https://github.com/comfyanonymous/ComfyUI) as backend.
As an alternative to the automatic installation, you can install it manually or
use an existing installation. If the server is already running locally before
starting Krita, the plugin will automatically try to connect. Using a remote
server is also possible this way.

Please check the list of [required extensions and models](https://docs.interstice.cloud/comfyui-setup) to make sure your installation is compatible.

### _Optional:_ Object selection tools (Segmentation)

If you're looking for a way to easily select objects or remove background in the
image, there is a [separate plugin](https://github.com/Acly/krita-ai-tools)
which adds AI segmentation tools.


## Contributing

Contributions are very welcome! Check the [contributing guide](CONTRIBUTING.md) to get started.

## <a name="gallery"></a> Gallery

_Live painting with regions (Click for video)_
[![Watch video demo](media/screenshot-regions.png)](https://youtu.be/PPxOE9YH57E "Watch video demo")

_Inpainting on a photo using a realistic model_
<img src="media/screenshot-2.png">

_Reworking and adding content to an AI generated image_
<img src="media/screenshot-1.png">

_Adding detail and iteratively refining small parts of the image_
<img src="media/screenshot-3.png">

_Modifying the pose vector layer to control character stances (Click for video)_
[![Watch video demo](media/screenshot-5.png)](https://youtu.be/-QDPEcVmdLI "Watch video demo")

_Control layers: Scribble, Line art, Depth map, Pose_
![Scribble control layer](media/control-scribble-screen.png)
![Line art control layer](media/control-line-screen.png)
![Depth map control layer](media/control-depth-screen.png)
![Pose control layer](media/control-pose-screen.png)

## Technology

* Image generation: [Stable Diffusion](https://github.com/Stability-AI/generative-models), [Flux](https://blackforestlabs.ai/)
* Diffusion backend: [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
* Inpainting: [ControlNet](https://github.com/lllyasviel/ControlNet), [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter)
