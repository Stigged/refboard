"""The right-click menu: the same actions as the keys and the tool panel, in one list.

It's a plain QMenu, styled with a "style sheet" (Qt's version of CSS) so it
matches the dark tool panel instead of the system theme.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

# Same Apple dark-mode colors as the tool panel and start panel.
MENU_STYLE = """
QMenu {
    background: #2C2C2E;
    border: 1px solid #3A3A3C;
    border-radius: 10px;
    padding: 5px;
}
QMenu::item {
    color: #E5E5EA;
    padding: 5px 16px 5px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #0A84FF;
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: #5A5A5E;
    background: transparent;
}
QMenu::separator {
    height: 1px;
    background: #3A3A3C;
    margin: 4px 8px;
}
"""


def show_context_menu(canvas, global_pos, scene_pos):
    """Pop up the menu at `global_pos` (screen pixels).

    `scene_pos` is the same spot on the canvas, where "Paste here" puts images.
    """
    menu = QMenu(canvas)
    menu.setStyleSheet(MENU_STYLE)
    # Without these the window behind the rounded corners stays square and gray.
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)

    selected = bool(canvas.selected_items())
    images = bool(canvas.selected_images())
    clipboard = QApplication.clipboard().mimeData()
    can_paste = clipboard is not None and (clipboard.hasUrls() or clipboard.hasImage() or clipboard.hasText())

    def add(text, action, enabled=True):
        # Text after a tab is shown on the right, as the shortcut hint.
        menu.addAction(text, action).setEnabled(enabled)

    add("Paste here\tCtrl+V", lambda: canvas.add_from_mime(
        QApplication.clipboard().mimeData(), scene_pos), can_paste)
    add("Add note here\tT", lambda: canvas.new_note_at(scene_pos))
    menu.addSeparator()
    add("Copy\tCtrl+C", canvas.copy_selected, selected)
    add("Duplicate\tCtrl+D", canvas.duplicate_selected, selected)
    add("Select all\tCtrl+A", canvas.select_all, bool(canvas.board_items()))
    menu.addSeparator()
    add("Bring to front\tCtrl+]", canvas.bring_to_front, selected)
    add("Send to back\tCtrl+[", canvas.send_to_back, selected)
    menu.addSeparator()
    add("Crop\tC", canvas.toggle_crop, images or canvas.crop_item is not None)
    add("Flip horizontally\tH", canvas.flip_horizontal, images)
    add("Flip vertically\tV", canvas.flip_vertical, images)
    add("Color\tG" if canvas.selected_all_gray() else "Black and white\tG", canvas.toggle_grayscale, images)
    add("Straighten", canvas.straighten_selected, canvas.any_selected_rotated())
    add("Delete\tDel", canvas.delete_selected, selected)
    menu.addSeparator()
    add("Arrange in rows\tA", canvas.arrange_selected, len(canvas.selected_items()) > 1)
    add("Fit all\tF", canvas.fit_all, bool(canvas.board_items()))

    menu.exec(global_pos)

