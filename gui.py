"""SP-404 MK2 Simple Converter - GUI using PySide6."""

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QThread, QObject, Signal, Slot, QThreadPool, QRunnable, QSize,
    QRect, QPoint,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QProgressBar,
    QGroupBox, QFileDialog, QMessageBox, QScrollArea, QStyle, QCheckBox,
    QAbstractItemView,
)
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon, QFont, QColor, QPainter

from converter import (
    convert_file, find_audio_files, check_ffmpeg, ConversionResult,
    SP404_SPEC,
)


class WorkerSignals(QObject):
    """Signals for conversion worker."""
    started = Signal(Path)
    progress = Signal(int, int)  # current, total
    finished = Signal(ConversionResult)
    error = Signal(str)


class ConvertWorker(QRunnable):
    """Worker for converting a single file in thread pool."""

    def __init__(
        self,
        input_path: Path,
        output_dir: Path,
        source_root: Optional[Path] = None,
        preserve_structure: bool = True,
        index: int = 0,
        total: int = 0,
    ):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.source_root = source_root
        self.preserve_structure = preserve_structure
        self.index = index
        self.total = total
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit(self.input_path)
        result = convert_file(
            self.input_path,
            self.output_dir,
            self.source_root,
            self.preserve_structure,
        )
        self.signals.finished.emit(result)
        self.signals.progress.emit(self.index, self.total)


class DropListWidget(QListWidget):
    """List widget with drag-and-drop support for folders/files."""

    files_dropped = Signal(list)  # list of Paths

    EMPTY_ICON_SIZE = 44

    def paintEvent(self, event):
        """Draw a placeholder (icon + hint) when the queue is empty.

        The default rendering is left untouched; the hint is only drawn on top
        so it disappears automatically as soon as items are present.
        """
        super().paintEvent(event)
        if self.count() > 0 or not self.isEnabled():
            return

        rect = self.viewport().rect()
        if rect.isEmpty():
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)

        # Icon: plain folder, centered above the hint text.
        icon = self.style().standardIcon(QStyle.SP_DirOpenIcon)
        icon_size = self.EMPTY_ICON_SIZE
        icon_rect = QRect(0, 0, icon_size, icon_size)
        icon_rect.moveCenter(QPoint(rect.center().x(), rect.center().y() - icon_size - 4))
        painter.setOpacity(0.35)
        icon.paint(painter, icon_rect)
        painter.setOpacity(1.0)

        # Primary hint
        font_main = QFont(self.font())
        font_main.setPointSizeF(11)
        font_main.setBold(True)
        painter.setFont(font_main)
        main_rect = QRect(
            rect.left(), icon_rect.bottom() + 12,
            rect.width(), int(font_main.pointSizeF() * 1.8),
        )
        painter.setPen(QColor("#d5dde5"))
        painter.drawText(main_rect, Qt.AlignHCenter | Qt.AlignTop, "Drop audio files or folders here")

        # Secondary hint: supported formats
        font_sub = QFont(self.font())
        font_sub.setPointSizeF(9)
        painter.setFont(font_sub)
        sub_rect = QRect(
            rect.left(), main_rect.bottom() + 4,
            rect.width(), int(font_sub.pointSizeF() * 1.6),
        )
        painter.setPen(QColor("#909197"))
        painter.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, "WAV · MP3 · FLAC · AIFF · OGG · M4A")

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        # QAbstractItemView requires a drag-drop mode != NoDragDrop to accept
        # external drops (Explorer); otherwise the OS shows the forbidden cursor.
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.viewport().setAcceptDrops(True)
        self.setSelectionMode(QListWidget.MultiSelection)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QListWidget {
                background-color: #242527;
                border: 2px dashed #909197;
                border-radius: 8px;
            }
            QListWidget[dragActive="true"] {
                border-color: #f2627d;
                background-color: #242527;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        # Accept drag for files and folders
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            self.viewport().update()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()

        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                # Use toLocalFile() which is standard for Windows
                local_path = url.toLocalFile()
                if local_path:
                    path = Path(local_path)
                    if path.exists():
                        paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SP-404 MK2 Simple Converter")
        # Accept files dropped anywhere on the window (fallback while the
        # QListWidget underneath handles its own drop area).
        self.setAcceptDrops(True)
        # Hard minimum so the window can never be shrunk below comfortable
        # proportions (everything must keep its size and place).
        MIN_W, MIN_H = 780, 700
        self.setMinimumSize(MIN_W, MIN_H)

        # Size the window relative to the current screen so the layout fits
        # any resolution and everything keeps its size and place.
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            w = max(int(geo.width() * 0.62), MIN_W)
            h = max(int(geo.height() * 0.80), MIN_H)
            self.resize(w, h)
            center = geo.center()
            self.move(int(center.x() - w / 2), int(center.y() - h / 2))
        else:
            self.resize(max(1000, MIN_W), max(700, MIN_H))

        # State
        self.pending_files: list[tuple[Path, Optional[Path]]] = []  # (file, source_root)
        self.output_dir: Optional[Path] = None
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(2)  # Limit concurrent conversions

        # Load stylesheet
        self.load_stylesheet()

        # Setup UI
        self.setup_ui()

        # Check ffmpeg on startup
        if not check_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg is required but not found in PATH.\n"
                "Please install FFmpeg and add it to your system PATH."
            )

    def load_stylesheet(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        style_path = base / "styles.qss"
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 16, 20, 16)

        # Title
        title = QLabel("SP-404 MK2 Simple Converter")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Drop zone / Queue
        queue_group = QGroupBox("Conversion queue")
        queue_layout = QVBoxLayout(queue_group)

        self.file_list = DropListWidget()
        self.file_list.files_dropped.connect(self.add_files)
        self.file_list.setMinimumHeight(140)
        queue_layout.addWidget(self.file_list)

        # Manual folder selection
        manual_controls = QHBoxLayout()
        self.browse_folder_btn = QPushButton("Add folder")
        self.browse_folder_btn.clicked.connect(self.browse_folder_manually)
        self.browse_folder_btn.setToolTip("Add")
        manual_controls.addWidget(self.browse_folder_btn)
        queue_layout.addLayout(manual_controls)

        # Queue controls
        queue_controls = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_queue)
        self.remove_btn = QPushButton("Delete selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        queue_controls.addWidget(self.clear_btn)
        queue_controls.addWidget(self.remove_btn)
        queue_controls.addStretch()
        queue_layout.addLayout(queue_controls)

        main_layout.addWidget(queue_group)

        # Output directory
        output_group = QGroupBox("Output Folder")
        output_layout = QVBoxLayout(output_group)
        output_row = QHBoxLayout()
        self.output_label = QLabel("Same folder as source")
        self.output_label.setObjectName("statusLabel")
        self.output_label.setWordWrap(True)
        self.browse_btn = QPushButton("Output folder")
        self.browse_btn.clicked.connect(self.choose_output_dir)
        output_row.addWidget(self.output_label, 1)
        output_row.addWidget(self.browse_btn)
        output_layout.addLayout(output_row)

        self.mirror_cb = QCheckBox("Preserve source folder structure")
        self.mirror_cb.setChecked(True)
        self.mirror_cb.setToolTip(
            "If enabled, converted files are saved by replicating the "
            "original folder structure within the output folder.\n"
            "If no output folder is specified, a folder named '<source>_sp' is created next to each "
            "source folder with the same structure."
        )
        output_layout.addWidget(self.mirror_cb)
        main_layout.addWidget(output_group)

        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        progress_layout.addWidget(self.overall_progress)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)

        main_layout.addWidget(progress_group)

        # Convert button
        self.convert_btn = QPushButton("Start")
        self.convert_btn.setObjectName("convertBtn")
        self.convert_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.convert_btn.setIconSize(QSize(20, 20))
        self.convert_btn.clicked.connect(self.start_conversion)
        self.convert_btn.setEnabled(False)
        main_layout.addWidget(self.convert_btn, alignment=Qt.AlignCenter)

        # Specs info
        specs_text = (
            f"{SP404_SPEC['recommended_sample_rate']} Hz | "
            f"{SP404_SPEC['bit_depth']}-bit | "
            f"{'Stereo' if SP404_SPEC['channels'] == 2 else 'Mono'} | "
            f"{SP404_SPEC['codec']} | .wav"
        )
        specs_label = QLabel(specs_text)
        specs_label.setObjectName("statusLabel")
        specs_label.setAlignment(Qt.AlignCenter)
        specs_label.setWordWrap(True)
        main_layout.addWidget(specs_label)

        # The queue is the flexible element: it absorbs extra vertical space
        # while every other section keeps its natural size and place.
        main_layout.setStretch(main_layout.indexOf(queue_group), 1)
        main_layout.setStretch(main_layout.indexOf(output_group), 0)
        main_layout.setStretch(main_layout.indexOf(progress_group), 0)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path and Path(local_path).exists():
                    paths.append(Path(local_path))
            if paths:
                self.add_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_files(self, paths: list[Path]):
        """Add files/folders to conversion queue."""
        new_pairs: list[tuple[Path, Optional[Path]]] = []
        for path in paths:
            if path.is_dir():
                # Recursively find audio files in folder, remembering the root
                for f in find_audio_files(path, recursive=True):
                    new_pairs.append((f, path))
            elif path.is_file():
                new_pairs.append((path, None))

        # Skip files that are already converted versions (*_sp.wav)
        new_pairs = [
            (f, root)
            for (f, root) in new_pairs
            if not f.stem.lower().endswith("_sp")
        ]

        # Deduplicate while preserving order
        seen = set()
        for f, root in new_pairs:
            resolved = f.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            self.pending_files.append((f, root))

        self.rebuild_list()
        self.update_convert_button()

    def rebuild_list(self):
        """Rebuild the queue list, grouping samples by their source folder."""
        self.file_list.setUpdatesEnabled(False)
        self.file_list.clear()

        groups: dict[Path, list[tuple[Path, Optional[Path]]]] = {}
        order: list[Path] = []
        for f, root in self.pending_files:
            parent = f.parent
            if parent not in groups:
                groups[parent] = []
                order.append(parent)
            groups[parent].append((f, root))

        for parent in order:
            items = groups[parent]
            header = QListWidgetItem(self.group_label(items[0][0], items[0][1]))
            header.setForeground(QColor("#f0c37b"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setFlags(Qt.ItemIsEnabled)  # header not selectable
            header.setToolTip(f"{len(items)} samples en {parent}")
            self.file_list.addItem(header)

            for f, root in items:
                item = QListWidgetItem(f"🎵  {f.name}")
                item.setData(Qt.UserRole, (f, root))
                item.setToolTip(str(f))
                self.file_list.addItem(item)

        self.file_list.setUpdatesEnabled(True)

    @staticmethod
    def group_label(file_path: Path, source_root: Optional[Path]) -> str:
        """Short label for a folder group (relative to pack root when possible)."""
        parent = file_path.parent
        if source_root is not None:
            try:
                rel = parent.relative_to(source_root)
                if rel == Path("."):
                    return f"📁  {source_root.name}"
                return f"📁  {source_root.name}\\{rel}"
            except ValueError:
                pass
        return f"📁  {parent}"

    def remove_selected(self):
        """Remove selected items from queue."""
        for item in self.file_list.selectedItems():
            pair = item.data(Qt.UserRole)
            if pair in self.pending_files:
                self.pending_files.remove(pair)
        self.rebuild_list()
        self.update_convert_button()

    def clear_queue(self):
        """Clear entire queue."""
        self.pending_files.clear()
        self.rebuild_list()
        self.update_convert_button()

    def choose_output_dir(self):
        """Select output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Set output folder")
        if dir_path:
            self.output_dir = Path(dir_path)
            self.output_label.setText(f"📁  {self.output_dir}")

    def browse_folder_manually(self):
        """Manually browse and add files from a folder."""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Set source"
        )
        if folder_path:
            folder = Path(folder_path)
            found = find_audio_files(folder, recursive=True)
            if found:
                self.add_files(found)
                self.status_label.setText(f"✓  added {len(found)} from {folder.name}")
            else:
                QMessageBox.information(
                    self,
                    "No files",
                    f"No audio files were found in: {folder_path}"
                )

    def update_convert_button(self):
        """Enable/disable convert button based on queue state."""
        has_files = len(self.pending_files) > 0
        self.convert_btn.setEnabled(has_files)
        self.convert_btn.setText(f"START ({len(self.pending_files)})" if has_files else "START")

    def start_conversion(self):
        """Start batch conversion."""
        if not self.pending_files:
            return

        self.convert_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.mirror_cb.setEnabled(False)
        self.file_list.setEnabled(False)

        self.overall_progress.setRange(0, len(self.pending_files))
        self.overall_progress.setValue(0)
        self.status_label.setText("Starting...")

        preserve = self.mirror_cb.isChecked()

        # Submit workers to thread pool
        for i, (file_path, source_root) in enumerate(self.pending_files):
            worker = ConvertWorker(
                file_path,
                self.resolve_output_base(file_path, source_root, preserve),
                source_root,
                preserve,
                i + 1,
                len(self.pending_files),
            )
            worker.signals.finished.connect(self.on_file_finished)
            worker.signals.progress.connect(self.on_progress_update)
            worker.signals.error.connect(self.on_error)
            self.thread_pool.start(worker)

    def resolve_output_base(
        self,
        file_path: Path,
        source_root: Optional[Path],
        preserve_structure: bool,
    ) -> Path:
        """Determine the base folder where the converted file will be placed.

        With an output folder + "preserve structure": the whole source pack is
        mirrored inside the output (output/<pack>/<subfolders>/...). Without an
        output folder: a <pack>_sp mirror is created next to the source.
        """
        if self.output_dir is not None:
            if preserve_structure and source_root is not None:
                return self.output_dir / source_root.name
            return self.output_dir
        if preserve_structure and source_root is not None:
            return source_root.parent / f"{source_root.name}_sp"
        return file_path.parent

    @Slot(ConversionResult)
    def on_file_finished(self, result: ConversionResult):
        """Handle single file conversion result."""
        if result.success:
            self.status_label.setText(f"✓  {result.input_path.name} → {result.output_path.name}")
        else:
            self.status_label.setText(f"✗  {result.input_path.name}: {result.error}")

    @Slot(int, int)
    def on_progress_update(self, current: int, total: int):
        """Update overall progress bar."""
        self.overall_progress.setValue(current)
        if current == total:
            self.conversion_complete()

    @Slot(str)
    def on_error(self, error: str):
        """Handle worker error."""
        self.status_label.setText(f"Error: {error}")

    def conversion_complete(self):
        """Called when all conversions finish."""
        self.convert_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.mirror_cb.setEnabled(True)
        self.file_list.setEnabled(True)
        self.status_label.setText("Conversion complete!")
        QMessageBox.information(self, "Complete", "All files have been processed.")


def is_elevated() -> bool:
    """Check if the current process runs with administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def load_app_icon() -> Optional[QIcon]:
    """Load the app icon (bundled in the exe or next to the source)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon_path = base / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SP-404 MK2 Simple Converter")
    app.setApplicationVersion("1.0.0")

    app_icon = load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()

    if is_elevated():
        QMessageBox.warning(
            window,
            "Running as administrator",
            "The application is running with administrator privileges.\n\n"
            "Windows may block drag and drop files from Explorer to "
            "(the prohibited cursor is shown).\n\n"
            "Close this instance and run it WITHOUT administrator privileges. "
            "(You can still use 'Add folder'.)"
        )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
