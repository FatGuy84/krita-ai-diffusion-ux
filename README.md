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

Upstream only has random wildcards `{a|b|c}`, where each generation picks one
option at random. This fork adds a **sequential** variant using double
brackets: `[[a|b|c]]`. Instead of picking randomly, batch item 1 gets `a`,
item 2 gets `b`, item 3 gets `c`, item 4 wraps back to `a`, and so on — useful
for systematically running through a fixed set of variations instead of
hoping the dice land right.

Multiple `[[...]]` groups in the same prompt combine into a **Cartesian
product** across the whole batch. For example:

```
[[black|white]] cat, [[sitting|jumping]]
```

generates all 4 combinations (black+sitting, black+jumping, white+sitting,
white+jumping) as batch items 1–4, then repeats. A button next to the batch
count (the dice/shuffle icon) reads the prompt and sets the batch count to
the exact number of combinations for you, so you don't have to count by hand.

`<lora:name:weight>` tags work inside `[[...]]` groups too, and are switched
correctly per batch item — each image in the batch is generated with its own
LoRA set rather than all of them sharing whatever LoRA the first prompt
evaluation picked (which is what happens upstream if you try this).

Other batch changes:
* **Batch count up to 1000** (upstream caps at 10), with a spinbox you can
  type into directly instead of only dragging a tiny slider.
* **Loop Generate**: a toggle button (circular arrow icon) next to Generate.
  Turning it on starts a batch immediately, and every time the queue empties
  it automatically enqueues another one — keeps running unattended (e.g.
  overnight) until you toggle it off again. If generation fails outright
  (bad prompt, disconnected server, etc.) it turns itself back off instead of
  spinning uselessly.

### LoRA Browser

Click the funnel icon in the prompt field to open a visual LoRA picker
instead of typing `<lora:...>` tags from memory or scrolling a giant
dropdown. It talks to [ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)
if you have it installed, and falls back to a plain file-name list otherwise
(no crash, just fewer features — no previews/tags/trigger words).

With Lora Manager available you get:
* **Preview thumbnails** for every LoRA, loaded lazily as you scroll so
  opening the browser with hundreds of LoRAs doesn't stall
* **Search** by name, **tag filter**, and a **base-model filter**
  (SD1.5/SDXL/Illustrious/Pony/Flux/etc.)
* **Favorites**, synced with whatever you've starred in Lora Manager itself
* **Trigger words** pulled from CivitAI metadata — insert them alongside the
  LoRA tag with one click, either a specific phrase group or all of them
* **Adjustable thumbnail size** via a slider, and the whole list is cached to
  disk so reopening the browser is instant instead of re-querying the server

**Multi-select** (Ctrl/Shift-click) lets you pick several LoRAs at once and
insert them as a single wildcard group — random `{a|b}` or sequential
`[[a|b]]`, matching the wildcard syntax above — with each LoRA's trigger
words carried along automatically. This is the fast way to set up "try LoRA
A, then B, then C" batches without manually typing out the wildcard syntax.

The dialog is non-modal, so Krita stays fully usable while it's open — no
need to close it before painting or switching layers.

### Style Picker

If you have more than a couple dozen style presets, the stock dropdown
becomes unusable — hundreds of entries in one scrolling list with no way to
search. This fork replaces it with the same kind of searchable, non-modal
picker dialog as the LoRA browser. Click the style name/icon button
(where the dropdown used to be) to open it.

* **Live search** by style name or checkpoint file name
* **Base-model family filter**, including a **"Base Model Family" field**
  added to every style (editable in the style editor's advanced checkpoint
  section, next to Architecture). Illustrious and Pony checkpoints use the
  exact same architecture as SDXL — there is no way to tell them apart from
  the model weights themselves — so this field defaults to a guess based on
  the checkpoint's file name ("Auto") but can be overridden by hand from a
  dropdown if the guess is wrong, and that's what the picker's filter uses
* **Favorite styles**: right-click a style or hit `F` to star it; favorites
  get pinned in their own section above the existing "Recently Used" list
  (upstream already sorts by recent use — this just adds the same idea for
  styles you always come back to, regardless of recency)

### Faster startup

**Model list disk cache**: upstream re-queries the server for every single
checkpoint/LoRA/etc. on every Krita startup, which is slow with large model
libraries (700+ entries easily takes a while). This fork caches the
discovered model list to disk per server URL, so subsequent startups load
instantly from cache. Click the Refresh button in the connection settings
after installing new models to force a re-scan.

### History & export

* **Split prompt actions**: upstream's "Copy Prompt" context-menu action both
  copied to clipboard *and* overwrote your current prompt field in one click,
  which is surprising if you only wanted one of those. Now there are four
  separate entries: Apply/Copy × raw/evaluated prompt.
* **Search the generation history**: a search box above the history list
  filters by prompt text live as you type (matches the raw and evaluated
  positive/negative prompts).
* **Favorite / Applied filters**: two toggle buttons above the history —
  one shows only images you've starred as favorites, the other shows only
  images you've actually applied to the canvas. Combine with the search box
  to narrow down a long history fast.
* **Favorite images**: right-click a result or hit `F` to mark it as a
  favorite — shown as a white star badge in the corner of the thumbnail
  (distinct from the existing "applied to canvas" badge in the opposite
  corner). Favorites are saved into the document and survive closing and
  reopening it.
* **Preview size slider**: a slider above the history resizes all thumbnails
  live, from small (fit more on screen) to large (see detail without
  clicking through). Thumbnails are always regenerated from the
  full-resolution result, so they stay sharp at any size.
* **Save to Eagle**: if you use [Eagle](https://eagle.cool) to organize
  reference images, right-click a result → "Save to Eagle" sends it straight
  into your library via Eagle's local API, with the prompt as the item
  title, full generation metadata (seed, sampler, LoRAs, etc.) as the
  annotation, and the style/LoRA names as tags — no manual export/import
  round-trip through the filesystem.

### Custom workflows

Ready-made Krita-adapted ComfyUI workflows live in
[`custom_workflows/`](custom_workflows/), for the
[Krea 2 Identity Edit](https://huggingface.co/conradlocke/krea2-identity-edit)
model. This requires the
[comfyui-krea2edit](https://github.com/lbouaraba/comfyui-krea2edit) custom
node pack installed on your ComfyUI server (the model uses dual conditioning
that stock ComfyUI nodes can't provide).

* **Krea2 Identity Edit** — single reference: the current Krita canvas is
  both the scene and the identity source for the edit.
* **Krea2 Identity Edit (Character + Scene)** — two references: the canvas
  provides the scene, and a second, selectable Krita layer provides the
  person/character reference to composite in. Handy for "put this character
  into this scene" style edits.

Both workflows expose the prompt, `grounding_px` (edit strength/precision),
and **two stackable LoRA slots** as regular Krita parameters — the LoRA
slots are populated from a dropdown of every LoRA your server knows about,
same as a normal style, so you can layer character/style LoRAs on top of the
edit without touching the underlying ComfyUI graph.

To use them, copy the `.json` files from `custom_workflows/` into
`%APPDATA%\krita\ai_diffusion\workflows\`, then pick the workflow from the
Custom workspace's workflow dropdown in Krita.

### Fixes

* **Refresh Models button was a no-op for the "missing models" warning**:
  clicking Refresh after installing a missing model correctly re-scanned the
  server, but the connection panel's warning banner never updated to reflect
  it — you had to fully disconnect and reconnect to make the stale warning
  go away. Refresh now updates the banner immediately.
* **Custom workflow graphs without a style node crashed on every generate**:
  any custom ComfyUI graph that doesn't include a `ETN_KritaStyleAndPrompt`
  node (e.g. a plain face-swap workflow) hit an unguarded `None` access and
  threw an error on every single generation attempt. Fixed.

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
