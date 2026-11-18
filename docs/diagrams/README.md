# Diagrams

This folder holds the diagrams that the repository `README.md` embeds, for anyone adding or editing one.

| File | Role |
|---|---|
| `<name>.mmd` | Mermaid source. It holds every node, edge, edge label and `%%` note of the diagram. |
| `<name>.svg` | Hand-written SVG of the matching `.mmd`. `README.md` embeds this file. |

## Editing a diagram

1. Edit `<name>.mmd`.
2. Edit `<name>.svg` by hand to match. The SVG is not generated.
3. Run the check below and open both PNGs.
4. Update the image alt text in `README.md` when the content changes.

## Style

The SVGs follow `SVG-STYLE.md` in the `aci-assessment` repository. These rules of that guide apply unchanged:

- Every node, edge, edge label and subgraph of the `.mmd` appears in the SVG.
- Every `%%` note of the `.mmd` appears in the CONSTRAINTS panel.
- The SVG states no fact that is missing from the `.mmd`.
- The `<style>` and `<defs>` blocks are identical to those in `sno.svg` of that repository.

The diagrams here differ from the guide in these values:

| Item | `SVG-STYLE.md` | Here | Reason |
|---|---|---|---|
| Canvas width | 1262 | 840 | GitHub shows a README image at most about 830 px wide on the repository home page. A 1262 px canvas is scaled to 66%, which draws 11 px text at about 7 px. |
| Content margin | x = 40 to 1222 | x = 40 to 800 | Follows from the canvas width. |
| CONSTRAINTS panel | Top-right panel or full-width band | Full-width band only: `x="40"`, `width="760"` | The top-right panel is 622 px wide and leaves no room for cards on an 840 px canvas. |
| Card columns | Not specified; `sno.svg` uses four columns of 264 px | Three columns. `azure-credential-flow.svg`: 216 px each with 56 px gaps. `aws-credential-flow.svg`: 240, 264 and 200 px with 28 px gaps. | Follows from the canvas width. The 56 px gap holds a short edge label above a horizontal edge. The unequal columns fit monospace resource names of up to 34 characters. |
| File location | `diagrams/` and `diagrams/svg/` | `docs/diagrams/`, `.mmd` and `.svg` side by side | This repository has no delivery folder. |

GitHub loads the SVG as an image, so the dark palette follows the viewer's operating system setting and not the GitHub theme. The canvas background is part of the SVG, so both palettes stay readable on either theme.

## Check

Prerequisites: a checkout of the `aci-assessment` repository with `npm install --prefix tools` done, and Node.js 22.12 or later.

```bash
node <aci-assessment>/tools/svgcheck.cjs --out /tmp/svg-renders docs/diagrams/*.svg
```

Expected output: `<name>: OK` for each file, then `2/2 OK · renders in /tmp/svg-renders`. The checker writes `<name>-light.png` and `<name>-dark.png`. Review both:

1. Both renders show every element.
2. Arrow tips touch card borders, no edge crosses a card, and no label sits on a line.
3. Every node, edge, label and `%%` note of the `.mmd` is present.
