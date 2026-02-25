from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import (
    QIcon,
    QTextListFormat,
    QTextCharFormat,
    QTextBlockFormat,
    QFont,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

# .../apps/DMT/src/ui/widgets/rich_text_editor.py -> .../apps/DMT/assets/icons
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icons"))


class FloatingFormattingToolbar(QWidget):
    def __init__(self, editor: QTextEdit, parent: QWidget) -> None:
        super().__init__(parent)
        self._editor = editor
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("FloatingToolbarWrapper")
        
        self.container = QFrame(self)
        self.container.setObjectName("ToolPanelContainer")
        self.container.setStyleSheet("""
            #ToolPanelContainer {
                background-color: rgba(9, 9, 11, 180);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 20);
            }
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px;
                margin: 2px;
                text-align: center;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QToolButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QToolButton:checked {
                background-color: rgba(255, 255, 255, 50);
                border: 1px solid rgba(255, 255, 255, 80);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(4)
        
        # Bold
        self._bold_btn = self._make_tool_button("Bold", os.path.join(ICON_DIR, "bold.svg"))
        self._bold_btn.setCheckable(True)
        self._bold_btn.clicked.connect(self._toggle_bold)
        container_layout.addWidget(self._bold_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Italic
        self._italic_btn = self._make_tool_button("Italic", os.path.join(ICON_DIR, "italic.svg"))
        self._italic_btn.setCheckable(True)
        self._italic_btn.clicked.connect(self._toggle_italic)
        container_layout.addWidget(self._italic_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Underline
        self._underline_btn = self._make_tool_button("Underline", os.path.join(ICON_DIR, "underline.svg"))
        self._underline_btn.setCheckable(True)
        self._underline_btn.clicked.connect(self._toggle_underline)
        container_layout.addWidget(self._underline_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Bullet List
        self._list_btn = self._make_tool_button("Bullet List", os.path.join(ICON_DIR, "list.svg"))
        self._list_btn.clicked.connect(self._toggle_list)
        container_layout.addWidget(self._list_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # Indent
        self._indent_btn = self._make_tool_button("Indent (Sub-bullet)", os.path.join(ICON_DIR, "indent.svg"))
        self._indent_btn.clicked.connect(self._indent)
        container_layout.addWidget(self._indent_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Outdent
        self._outdent_btn = self._make_tool_button("Outdent", os.path.join(ICON_DIR, "outdent.svg"))
        self._outdent_btn.clicked.connect(self._outdent)
        container_layout.addWidget(self._outdent_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        
        container_layout.addStretch(1)

        container_layout.addStretch(1)

        # Font Size Control (Custom Layout)
        # Field on top, two buttons (Up/Down) below
        font_control_frame = QWidget()
        font_control_layout = QVBoxLayout(font_control_frame)
        font_control_layout.setContentsMargins(0, 0, 0, 0)
        font_control_layout.setSpacing(2)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(8, 72)
        self._size_spin.setValue(12)
        self._size_spin.setSuffix("pt")
        self._size_spin.setToolTip("Font Size")
        # Hide default buttons
        self._size_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._size_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Enforce Click Focus ONLY
        self._size_spin.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._size_spin.valueChanged.connect(self._set_font_size)
        self._size_spin.setFixedWidth(46) # Matches 2 buttons (22*2 + 2 spacing)
        
        self._size_spin.setStyleSheet("background-color: rgba(0,0,0,100); border-radius: 4px; padding: 2px;")
        # Prevent scroll wheel from accidentally changing value when scrolling page
        self._size_spin.wheelEvent = lambda event: event.ignore() 
        font_control_layout.addWidget(self._size_spin)
        
        # Buttons Container
        btns_frame = QWidget()
        btns_layout = QHBoxLayout(btns_frame)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(2)
        
        # Up Button
        self._up_btn = QToolButton()
        # Use existing white icons if available or standard ones
        # Assuming caret_up_white.svg exists as I saw it in file list
        self._up_btn.setIcon(QIcon(os.path.join(ICON_DIR, "caret_up_white.svg")))
        self._up_btn.setFixedSize(22, 18) # Smaller
        self._up_btn.clicked.connect(self._size_spin.stepUp)
        self._up_btn.setStyleSheet("QToolButton { background-color: rgba(0,0,0,100); border-radius: 4px; padding: 0px; margin: 0px; min-width: 22px; max-width: 22px; min-height: 18px; max-height: 18px; } QToolButton:hover { background-color: rgba(255,255,255,30); }")
        
        # Down Button
        self._down_btn = QToolButton()
        self._down_btn.setIcon(QIcon(os.path.join(ICON_DIR, "caret_down_white.svg")))
        self._down_btn.setFixedSize(22, 18)
        self._down_btn.clicked.connect(self._size_spin.stepDown)
        self._down_btn.setStyleSheet("QToolButton { background-color: rgba(0,0,0,100); border-radius: 4px; padding: 0px; margin: 0px; min-width: 22px; max-width: 22px; min-height: 18px; max-height: 18px; } QToolButton:hover { background-color: rgba(255,255,255,30); }")

        btns_layout.addWidget(self._up_btn)
        btns_layout.addWidget(self._down_btn)
        
        font_control_layout.addWidget(btns_frame)
        
        container_layout.addWidget(font_control_frame, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # Connect cursor changes to update UI state
        self._editor.cursorPositionChanged.connect(self._update_ui_state)


    def mousePressEvent(self, event) -> None:
        """Handle clicks on the toolbar background to unfocus inputs."""
        # Transfer focus back to the editor to unfocus the spinbox
        self._editor.setFocus()
        super().mousePressEvent(event)

    def clear_spinbox_focus(self) -> None:
        if self._size_spin.hasFocus():
            self._size_spin.clearFocus()
            le = self._size_spin.findChild(QLineEdit)
            if le:
                le.deselect()


    def _make_tool_button(self, tooltip: str, icon_path: str) -> QToolButton:
        btn = QToolButton()
        # Fallback text if icon missing
        btn.setText(tooltip[0])
        if os.path.exists(icon_path):
            btn.setIcon(QIcon(icon_path))
        btn.setToolTip(tooltip)
        btn.setIconSize(QSize(20, 20))
        btn.setFixedSize(32, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_click_focus_only(btn)
        return btn

    def _set_click_focus_only(self, widget: QWidget) -> None:
        widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def _toggle_bold(self) -> None:
        cursor = self._editor.textCursor()
        fmt = cursor.charFormat()
        weight = QFont.Weight.Bold if fmt.fontWeight() != QFont.Weight.Bold else QFont.Weight.Normal
        fmt.setFontWeight(weight)
        self._apply_format(fmt)

    def _toggle_italic(self) -> None:
        cursor = self._editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontItalic(not fmt.fontItalic())
        self._apply_format(fmt)

    def _toggle_underline(self) -> None:
        cursor = self._editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        self._apply_format(fmt)
        
    def _set_font_size(self, size: int) -> None:
        cursor = self._editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontPointSize(size)
        self._apply_format(fmt)
        
        # Prevent the number from being selected (highlighted)
        # Use QTimer to ensure this runs after internal QSpinBox handling
        QTimer.singleShot(0, self._size_spin.lineEdit().deselect)

    def _toggle_list(self) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        
        list_fmt = QTextListFormat()
        list_fmt.setStyle(QTextListFormat.Style.ListDisc)
        
        # Check if already in a list
        current_list = cursor.currentList()
        if current_list:
             # Remove list format by applying standard block format
             block_fmt = QTextBlockFormat()
             block_fmt.setIndent(0)
             cursor.setBlockFormat(block_fmt)
        else:
             cursor.createList(list_fmt)
             
        cursor.endEditBlock()
        self._editor.setFocus()

        self._editor.setFocus()

    def _indent(self) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        
        current_list = cursor.currentList()
        if current_list:
            # Create a new sub list format with increased indentation
            list_fmt = current_list.format()
            list_fmt.setIndent(list_fmt.indent() + 1)
            cursor.createList(list_fmt)
        else:
            # If not a list, just indent the block
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(block_fmt.indent() + 1)
            cursor.setBlockFormat(block_fmt)
            
        cursor.endEditBlock()
        self._editor.setFocus()

    def _outdent(self) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        
        current_list = cursor.currentList()
        if current_list:
            list_fmt = current_list.format()
            if list_fmt.indent() > 1:
                list_fmt.setIndent(list_fmt.indent() - 1)
                cursor.createList(list_fmt)
            else:
                new_indent = list_fmt.indent() - 1
                if new_indent > 0:
                    list_fmt.setIndent(new_indent)
                    cursor.createList(list_fmt)
                else:
                     # Remove list
                     block_fmt = QTextBlockFormat()
                     block_fmt.setIndent(0) # Or keep block indent?
                     cursor.setBlockFormat(block_fmt)
        else:
            block_fmt = cursor.blockFormat()
            if block_fmt.indent() > 0:
                block_fmt.setIndent(block_fmt.indent() - 1)
                cursor.setBlockFormat(block_fmt)

        cursor.endEditBlock()
        self._editor.setFocus()

    def _apply_format(self, fmt: QTextCharFormat) -> None:
        cursor = self._editor.textCursor()
        cursor.mergeCharFormat(fmt)
        
        # Fixing Bullet Point Sizing Issue
        # If we are in a list, we might need to update the block's char format
        # so that the bullet (which falls back to block format) resizes correctly.
        # This is especially crucial for the first line or when the bullet depends on the first char.
        if cursor.currentList():
            # Apply to the block char format as well to ensure bullet resizes
            cursor.mergeBlockCharFormat(fmt)

        self._editor.mergeCurrentCharFormat(fmt)
        self._editor.setFocus()
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        cursor = self._editor.textCursor()
        fmt = cursor.charFormat()
        
        self._bold_btn.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self._italic_btn.setChecked(fmt.fontItalic())
        self._underline_btn.setChecked(fmt.fontUnderline())
        
        size = fmt.fontPointSize()
        if size > 0:
            self._size_spin.blockSignals(True)
            self._size_spin.setValue(int(size))
            self._size_spin.blockSignals(False)


class RichTextDescriptionEditor(QTextEdit):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Description, notes, and notable traits")

        self.setAcceptRichText(True)
        # Ensure widget doesn't produce scrollbar by text reaching viewport edge needlessly
        # But wait, resizing viewport margins works, but sometimes scrollbar logic is finicky.
        # User constraint: "scroll bar on the bottom which should never happen just make the actual textbox slightly smaller"
        # We can enforce "WordWrap" and NO Horizontal Scrollbar policy
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        self._toolbar = FloatingFormattingToolbar(self, self)
        
        # Set initial font size to 12
        cursor = self.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontPointSize(12)
        # Apply to both current char format (for typing) and block format (for initial line height/bullets)
        cursor.mergeCharFormat(fmt)
        cursor.mergeBlockCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)
        
        self._toolbar.show()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)

        if hasattr(self, '_toolbar'):
            self._toolbar.clear_spinbox_focus()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if hasattr(self, '_toolbar'):
            self._toolbar.clear_spinbox_focus()


        
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Position toolbar centered on the right edge, floating over content.
        tb_size = self._toolbar.sizeHint()
        # Ensure scrollbar doesn't cover it (Vertical scrollbar)
        margin = 20 if self.verticalScrollBar().isVisible() else 5
        x = self.width() - tb_size.width() - margin
        y = max(0, (self.height() - tb_size.height()) // 2)  # Center vertically
        self._toolbar.move(x, y)
        self._toolbar.resize(tb_size)
        
        # Add viewport margin so text doesn't go under the toolbar
        # Right margin = toolbar width + spacing
        # This effectively makes the "textbox slightly smaller" on the right side
        right_margin = tb_size.width() + margin + 5
        self.setViewportMargins(0, 0, right_margin, 0)
