# Quirks & Common Issues

## 1. SVG Colors
- **Issue**: SVGs rendered in black or dark colors are often invisible on the application's default dark theme.
- **Solution**: Always ensure SVG icons use white (`#FFFFFF`) or bright colors for `stroke` or `fill` unless they are strictly intended for a light background.

## 2. Square Buttons
- **Issue**: Buttons (especially `QToolButton`) with global styles like `PrimaryButton` or `DestructiveButton` have default horizontal padding (e.g., `6px 12px`), which forces them to be rectangular even if `setFixedSize()` is used.
- **Solution**: To make a button perfectly square (e.g., 32x32), you must override the global stylesheet padding inline:
  ```python
  button.setFixedSize(32, 32)
  button.setStyleSheet("padding: 4px; border-radius: 6px;") # Adjust values as needed
  ```

## 3. Ghost Dialogs / White Window Flashing
- **Issue**: Strange white rectangles or blank windows  briefly flash on the screen when opening certain applets (especially the Item Creator).
- **Cause**: In Qt, any widget created without a parent (e.g., `button = QPushButton()`) is treated as a top-level window by the operating system. During high-volume initialization (like the icon grid), the OS tries to briefly spawn these as standalone windows before they are nested in layouts, causing a "strobe" effect of blank white windows.
- **Solution**: Always provide a parent to widget constructors to ensure they are born "attached" to the UI hierarchy:
  ```python
  # WRONG - spawns a ghost window briefly
  button = QToolButton() 

    # CORRECT - tells Qt this belongs to the container
    button = QToolButton(self.container)
    ```

## 4. Global QSS Not Applying To Child Buttons
- **Issue**: Applying `setStyleSheet(...)` directly to a parent container (even just `background-color: transparent`) blocks global QSS rules from `app.py` on child widgets. This can make `QToolButton#PrimaryButton/#DestructiveButton/#SecondaryButton` lose their filled backgrounds and look unstyled.
- **Cause**: Qt treats any explicit stylesheet on a widget as a boundary; global styles no longer cascade into its children.
- **Solution**: Use the shared transparent styling via `setObjectName("TransparentContainer")` (or another existing object name from the global stylesheet) instead of setting a local stylesheet on the parent.
  ```python
  container = QWidget(parent)
  container.setObjectName("TransparentContainer")  # keeps transparency without breaking global QSS
  ```

## 5. QFont::setPointSize Warning On Hover
- **Issue**: `QFont::setPointSize: Point size <= 0 (-1)` warnings appear when hovering certain widgets that use QSS `font-size`.
- **Cause**: Some default Qt fonts report a point size of `-1` (unset). When QSS tries to adjust `font-size` on hover, Qt attempts to apply an invalid point size.
- **Solution**: Avoid `font-size` in QSS for these widgets. Instead, set an explicit font on the widget:
  ```python
  font = button.font()
  if font.pointSize() <= 0:
      font.setPointSize(12)
  button.setFont(font)
  ```
  If you must use QSS, prefer `setPixelSize(...)` on the `QFont` and remove `font-size` from the stylesheet.

## 6. Transparent PDF Viewer Background (Player Sheets)
- **Issue**: The PDF viewer margins showed as black even when the surrounding panel was set to transparent.
- **Cause**: Qt was still erasing backgrounds for the PDF viewer and its scroll area/viewport, so “transparent” content rendered against a black backing store.
- **Solution**: Make every layer in the chain truly transparent:
  - **PdfiumViewerWidget**: disable system background erasing and avoid any background fill:
    - `setAutoFillBackground(False)`
    - `setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)`
    - `setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)`
    - Do **not** `fillRect` with black (or any color) in `paintEvent`.
  - **CharacterSheetPanel scroll area**: the `QScrollArea` and its `viewport()` must also be transparent:
    - `setAutoFillBackground(False)`
    - `setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)`
    - `viewport().setAutoFillBackground(False)`
    - `viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)`
    - `viewport().setObjectName("TransparentContainer")` (so global QSS keeps it transparent)
  - **Panel background**: if the containing panel is meant to be transparent, use a transparent panel style (e.g., `PanelTransparent`) so only the border remains glassy.

## 7. Pixely/Soft Rendering in PDF + Previews (HiDPI)
- **Issue**: PDF pages and thumbnail/previews can look soft or slightly pixely, especially on Windows scaling (125%/150%/200%) or mixed-DPI monitor setups.
- **Primary cause**: Rendering buffers were created at logical size only (no device pixel ratio), then upscaled by Qt/compositor.
- **Solution (PDF pages)**:
  - Render offscreen buffers at `logical_size * devicePixelRatioF()`.
  - Set DPR on the resulting `QImage/QPixmap` (`setDevicePixelRatio(dpr)`), so Qt paints it at correct logical size.
  - Include DPR in render cache keys (e.g., `(page, zoom, dpr_key)`), not just page/zoom.
  - For PDFium bitmap rendering, enabling `FPDF_RENDER_FORCEHALFTONE` helps downscaled embedded images look cleaner.

- **Issue**: Dungeon/map previews looked crisp initially but went soft after layout resize.
- **Primary cause**: Cached preview pixmaps were reused after icon-size or DPI changes.
- **Solution (preview caches)**:
  - Store a preview signature with each cached preview (at minimum width, height, DPR key).
  - Regenerate previews when signature changes, not only when preview is null.
  - For scene->image preview rendering, enable:
    - `QPainter::Antialiasing`
    - `QPainter::TextAntialiasing`
    - `QPainter::SmoothPixmapTransform`

- **Issue**: Equipment/item icons looked soft in slots.
- **Primary cause**: `QLabel.setScaledContents(True)` performs implicit scaling and can produce poorer results, especially with repeated resizes.
- **Solution (slot icons)**:
  - Prefer explicit pre-scaling via `pixmap.scaled(..., SmoothTransformation)` at target size * DPR.
  - Set DPR on the scaled pixmap.
  - Cache expensive generated backgrounds by `(size, dpr)` to avoid quality/perf regressions.

- **Issue**: Hover item previews in Player Sheets looked soft on laptop/smaller-window layouts.
- **Primary cause**: Preview cards were rendered/cached at one fixed tooltip width and then downscaled again to fit the silhouette frame in narrow layouts; cache keys ignored DPR and bounds, so HiDPI displays reused non-DPR pixmaps.
- **Solution (hover previews)**:
  - Render preview pixmaps for the actual display bounds (`max_width`, `max_height`) and current screen DPR.
  - Include `item_id + max_width + max_height + dpr` in preview cache keys.
  - Set `setDevicePixelRatio(dpr)` on preview pixmaps and use device-independent size for layout/placement checks.
  - If fallback shrinking is needed, always scale from the original preview source, not repeatedly from already-shrunk pixmaps.

- **Issue**: Map list thumbs stayed low quality after source image updates.
- **Primary cause**: Existing thumbnail files were reused unconditionally.
- **Solution (thumbnail freshness)**:
  - Regenerate thumbs when source mtime is newer than thumb mtime.
  - Regenerate if thumb resolution is below current quality target.

## 8. Qt Button Clipping + Size Mismatch (Deep-Dive Playbook)
- **Issue**: Header/tool buttons (e.g., inventory toggles vs add/remove buttons) look different in height, or bottom pixels are clipped even though `setFixedSize(...)`/`setFixedHeight(...)` appears correct.

- **Root cause pattern**:
  - Global QSS for object names (for example `QToolButton#PrimaryButton`, `QToolButton#DestructiveButton`, `QToolButton#InventoryToggleButton`) can override effective min/max heights through `padding` and style metrics.
  - Inline `setStyleSheet(...)` can change computed size hints in non-obvious ways.
  - The parent header/container may be shorter than the final rendered control height.
  - Result: controls end up with different actual heights and can render outside parent bounds (visual clipping at bottom).

- **How to debug quickly (repeatable)**:
  1. Create the widget in an offscreen Qt test or script with the real app stylesheet applied.
  2. Print **runtime geometry and constraints** for each affected button:
     - `geometry()`
     - `height()`
     - `sizeHint().height()`
     - `minimumSizeHint().height()`
     - `minimumHeight()` / `maximumHeight()`
     - current inline stylesheet string
  3. Print parent/header geometry and compare global top/bottom for each button.
  4. If a button bottom is below header bottom, this is not a paint-order bug; it is a size/constraints mismatch.
  5. Temporarily vary only `padding` in inline QSS (`0px`, `2px`, `4px`) and observe resulting effective height to identify which style rule is inflating size.

- **Fix pattern that works reliably**:
  - Pick one target rendered height for all controls in the row (for example `42px`).
  - Ensure the header/container height is safely larger (for example `48px`) and remove extra vertical layout margins unless needed.
  - For each button class in that row:
    - enforce identical fixed height/size in code;
    - align inline QSS padding so all classes compute to the same effective height;
    - avoid contradictory constraints (`setFixedSize` + QSS that forces larger min-height).
  - If global QSS still introduces class-specific drift, add narrow inline overrides per object name in that widget only.

- **Verification checklist**:
  - All buttons in the row have the same runtime `height()`.
  - Global button rects are fully contained inside the header rect.
  - Visual baseline/centering is the same for toggles and icon-only buttons.
  - Add a regression UI test that asserts:
    - equal heights,
    - near-equal center Y,
    - full containment inside header bounds.

## 9. Equipment Slot Pixel Offset at Fractional DPI (Player Sheets)
- **Issue**: Equipped item icons looked shifted relative to the slot frame/background, and which slots looked "off" changed with window size.
- **Primary cause**: The slot frame/background/icon were rendered in separate UI layers (styled frame plus separate labels), so at fractional DPI (for example Windows `125%`) each layer could land on different subpixel rounding paths during composition.
- **Symptom pattern**:
  - At `100%` scale, alignment looked correct.
  - At fractional scale, offset was usually `1px` and changed by slot position and window size.
  - Weapon slots looked worse first only because their positions hit problematic fractional coordinates more often.
- **Fix that solved it**:
  - Render the whole slot in one raster pass:
    - slot base fill,
    - placeholder background,
    - equipped item icon,
    - border/selection/dragover outline.
  - Use one canvas label (`_slot_canvas`) per slot and rebuild that single pixmap when size/item/state changes.
  - Keep drag pixmap sourced from the same composed canvas, not from a different layer.
- **Why this works**: frame and icon no longer pass through independent Qt layout/paint stages, so they cannot drift relative to each other due to per-layer subpixel rounding.
- **Verification approach**:
  - Reproduce with `QT_QPA_PLATFORM=offscreen` and `QT_SCALE_FACTOR=1.25`.
  - Compare composed slot pixmaps across weapon/non-weapon slots for the same item.
  - If hashes are identical across slots/window sizes, relative frame-icon offset is removed.

## 10. White Focus Box Around Session List Text (Sessions Applet)
- **Issue**: Session names in the right toolbar/list showed an ugly white focus box around the text.
- **Cause**: The `QListWidget` item/editor focus rendering was still active, so focus artifacts appeared on top of custom `NavList` styling.
- **Solution**:
  - Disable focus visuals on the session list:
    - `self.session_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)`
  - Keep selection coloring controlled by explicit active/inactive selected-item styles (already in app stylesheet), so selection remains visible without the extra focus rectangle.
- **Result**: Selection stays styled correctly, and the white focus/text box artifact is removed.

## 11. Table Header and Row Alignment (Stats Table)
- **Issue**: Horizontal misalignment between table headers ("Value", "Stat") and content rows, and misalignment between the header background box and row selection shadows.
- **Root Cause**:
    - **Box Misalignment**: Default layout margins and component-level padding/border spacing in `QHeaderView` and `QTableWidget` differ by default (often causing an ~11px shift).
    - **Character Misalignment**: `QHeaderView::section` and `QTableWidget::item` have different internal rendering offsets for text/icons, even when `padding` is set equally in QSS.
- **Solution**:
    - **Flush Boxes**: Zero out all margins/padding for the container layout and the table components:
      ```python
      layout.setContentsMargins(0, 0, 0, 0)
      table.setStyleSheet("QTableWidget { padding: 0px; margin: 0px; }")
      ```
    - **Header Background**: Apply background color to the entire `QHeaderView` (not just `::section`) to ensure the background fills the full width and aligns with row shadows.
    - **Pixel-Matched Text**: Use a diagnostic script to measure the actual visual offset of row text and match the header's `padding-left` to that offset (e.g., if items are shifted 14px, set header `padding-left: 14px`).
    - **Square Buttons in Rows**: For small icon buttons (trash icons), use strict CSS `min-width/height` AND `max-width/height` to prevent global stylesheet rules from squashing the button into a rectangle.
