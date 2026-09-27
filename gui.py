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
    QAbstractItemView, QSizePolicy, QComboBox,
)
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon, QFont, QColor, QPainter

from converter import (
    convert_file, find_audio_files, check_ffmpeg, ConversionResult,
    SP404_SPEC, TARGET_SAMPLE_RATES,
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
        target_sample_rate: Optional[int] = None,
    ):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.source_root = source_root
        self.preserve_structure = preserve_structure
        self.index = index
        self.total = total
        self.target_sample_rate = target_sample_rate or int(SP404_SPEC["recommended_sample_rate"])
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit(self.input_path)
        result = convert_file(
            self.input_path,
            self.output_dir,
            self.source_root,
            self.preserve_structure,
            self.target_sample_rate,
        )
        self.signals.finished.emit(result)
        self.signals.progress.emit(self.index, self.total)


class DropListWidget(QListWidget):
    """List widget with drag-and-drop support for folders/files."""

    files_dropped = Signal(list)  # list of Paths

    EMPTY_ICON_SIZE = 36

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Icon: plain folder, centered above the hint text.
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        icon_size = self.EMPTY_ICON_SIZE
        icon_rect = QRect(0, 0, icon_size, icon_size)
        icon_rect.moveCenter(QPoint(rect.center().x(), rect.center().y() - icon_size - 4))
        painter.setOpacity(0.35)
        icon.paint(painter, icon_rect)
        painter.setOpacity(1.0)

        # Primary hint
        font_main = QFont(self.font())
        font_main.setPointSizeF(9)
        font_main.setBold(True)
        painter.setFont(font_main)
        main_rect = QRect(
            rect.left(), icon_rect.bottom() + 12,
            rect.width(), int(font_main.pointSizeF() * 1.8),
        )
        painter.setPen(QColor("#e5e5e5"))
        painter.drawText(
            main_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Drop files or folders",
        )

        # Secondary hint: supported formats
        font_sub = QFont(self.font())
        font_sub.setPointSizeF(7.5)
        painter.setFont(font_sub)
        sub_rect = QRect(
            rect.left(), main_rect.bottom() + 4,
            rect.width(), int(font_sub.pointSizeF() * 1.6),
        )
        painter.setPen(QColor("#92959a"))
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "WAV · MP3 · FLAC · AIFF · OGG · M4A",
        )

    def __init__(self):
        super().__init__()
        self.setObjectName("dropList")
        self.setAcceptDrops(True)
        # QAbstractItemView requires a drag-drop mode != NoDragDrop to accept
        # external drops (Explorer); otherwise the OS shows the forbidden cursor.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.viewport().setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.setAlternatingRowColors(True)

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
        # Fixed, non-resizable window: sized to the design but capped so it
        # never covers the whole screen.
        desired_w, desired_h = 1200, 360
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            w = int(min(desired_w, max(geo.width() - 48, 900)))
            h = int(min(desired_h, max(geo.height() - 48, 360)))
        else:
            w, h = desired_w, desired_h
        self.setFixedSize(w, h)

        # Center the window on screen.
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            center = geo.center()
            self.move(int(center.x() - self.width() / 2),
                      int(center.y() - self.height() / 2))

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

        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(16, 8, 16, 8)

        # Header
        title = QLabel("SP-404 MK2 Simple Converter")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFixedHeight(32)
        root.addWidget(title)

        # FILES | OUTPUT | PROGRESS (FILES dominant)
        sections_widget = QWidget()
        sections = QHBoxLayout(sections_widget)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(8)
        self._sections_widget = sections_widget
        files_panel = self._build_files_section()
        output_panel = self._build_output_section()
        progress_panel = self._build_progress_section()
        for p in (files_panel, output_panel, progress_panel):
            p.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._panels = (files_panel, output_panel, progress_panel)
        sections.addWidget(files_panel, 44)
        sections.addWidget(output_panel, 28)
        sections.addWidget(progress_panel, 28)
        root.addWidget(sections_widget, 1)

        # Footer: target format (updates with the sample-rate selector)
        self.specs_label = QLabel("")
        self.specs_label.setObjectName("footerLabel")
        self.specs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.specs_label.setFixedHeight(15)
        root.addWidget(self.specs_label)
        self.update_footer_label()

    def _build_files_section(self) -> QGroupBox:
        panel = QGroupBox("FILES")

        layout = QVBoxLayout(panel)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # Drop zone (compact, ~280-300 px tall)
        self.file_list = DropListWidget()
        self.file_list.files_dropped.connect(self.add_files)
        self.file_list.setMinimumHeight(150)
        self.file_list.setMaximumHeight(160)
        self.file_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        layout.addWidget(self.file_list)

        self.browse_folder_btn = QPushButton("Add folder")
        self.browse_folder_btn.setFixedHeight(32)
        self.browse_folder_btn.clicked.connect(self.browse_folder_manually)
        self.browse_folder_btn.setToolTip("Add a folder of samples")
        layout.addWidget(self.browse_folder_btn)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_queue)
        self.remove_btn = QPushButton("Delete selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.setFixedHeight(32)
        self.remove_btn.setFixedHeight(32)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.remove_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        return panel

    def _build_output_section(self) -> QGroupBox:
        panel = QGroupBox("OUTPUT")

        layout = QVBoxLayout(panel)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # Output selector row (~42 px tall box)
        row = QWidget()
        row.setObjectName("outputRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(38)
        row_layout = QHBoxLayout(row)
        row_layout.setSpacing(0)
        row_layout.setContentsMargins(12, 0, 4, 0)

        self.output_label = QLabel("Same folder as source")
        self.output_label.setObjectName("outputFieldText")
        self.output_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(self.output_label, 1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.choose_output_dir)
        row_layout.addWidget(self.browse_btn)
        layout.addWidget(row)

        self.mirror_cb = QCheckBox("Preserve source folder structure")
        self.mirror_cb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.mirror_cb.setChecked(True)
        self.mirror_cb.setToolTip(
            "If enabled, converted files are saved by replicating the "
            "original folder structure within the output folder.\n"
            "If no output folder is specified, a folder named '<source>_sp' is created next to each "
            "source folder with the same structure."
        )
        layout.addWidget(self.mirror_cb)

        # Sample-rate selector (SP-404 MK2 runs at 48 kHz internally)
        rate_row = QHBoxLayout()
        rate_row.setSpacing(8)
        rate_label = QLabel("Sample rate:")
        rate_label.setObjectName("statusLabel")
        rate_row.addWidget(rate_label)
        self.sample_rate_cb = QComboBox()
        self.sample_rate_cb.setToolTip(
            "Target sample rate. The SP-404 MK2 works internally at "
            "48 kHz / 16-bit, so 48 kHz is the native choice.\n"
            "Every file is forced to this rate (compatible files at a "
            "different rate are resampled, not just copied)."
        )
        for rate in TARGET_SAMPLE_RATES:
            if rate == 48000:
                self.sample_rate_cb.addItem("48 000 Hz (SP-404 native)", rate)
            elif rate == 44100:
                self.sample_rate_cb.addItem("44 100 Hz (legacy)", rate)
            else:
                self.sample_rate_cb.addItem(f"{rate} Hz", rate)
        self.sample_rate_cb.setCurrentIndex(0)
        self.sample_rate_cb.currentIndexChanged.connect(self.update_footer_label)
        rate_row.addWidget(self.sample_rate_cb, 1)
        layout.addLayout(rate_row)

        layout.addStretch(1)
        return panel

    def _build_progress_section(self) -> QGroupBox:
        panel = QGroupBox("PROGRESS")

        layout = QVBoxLayout(panel)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 12, 10, 12)

        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("%p%")
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFixedHeight(28)
        layout.addWidget(self.overall_progress)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        self.convert_btn = QPushButton("START")
        self.convert_btn.setObjectName("convertBtn")
        self.convert_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.convert_btn.setIconSize(QSize(15, 15))
        self.convert_btn.clicked.connect(self.start_conversion)
        self.convert_btn.setEnabled(False)
        self.convert_btn.setMinimumHeight(30)
        self.convert_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.convert_btn)

        return panel

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
            header.setForeground(QColor("#e8a33d"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # header not selectable
            header.setToolTip(f"{len(items)} samples en {parent}")
            self.file_list.addItem(header)

            for f, root in items:
                item = QListWidgetItem(f.name)
                item.setData(Qt.ItemDataRole.UserRole, (f, root))
                item.setToolTip(str(f))
                self.file_list.addItem(item)

        self.file_list.setUpdatesEnabled(True)
        self._update_drop_zone_height()

    def _update_drop_zone_height(self):
        """Compact drop zone when empty; expand when the queue has files."""
        if self.file_list.count() > 0:
            self.file_list.setMaximumHeight(16777215)
        else:
            self.file_list.setMaximumHeight(160)

    @staticmethod
    def group_label(file_path: Path, source_root: Optional[Path]) -> str:
        """Short label for a folder group (relative to pack root when possible)."""
        parent = file_path.parent
        if source_root is not None:
            try:
                rel = parent.relative_to(source_root)
                if rel == Path("."):
                    return f"{source_root.name}"
                return f"{source_root.name}\\{rel}"
            except ValueError:
                pass
        return str(parent)

    def remove_selected(self):
        """Remove selected items from queue."""
        for item in self.file_list.selectedItems():
            pair = item.data(Qt.ItemDataRole.UserRole)
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
            elided = self.output_label.fontMetrics().elidedText(
                str(self.output_dir), Qt.TextElideMode.ElideMiddle, 260
            )
            self.output_label.setText(elided)
            self.output_label.setToolTip(str(self.output_dir))

    def browse_folder_manually(self):
        """Manually browse and add files from a folder."""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Set source"
        )
        if folder_path:
            folder = Path(folder_path)
            found = find_audio_files(folder, recursive=True)
            if found:
                self.add_files([folder])
                self.status_label.setText(f"Added {len(found)} from {folder.name}")
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

    def selected_sample_rate(self) -> int:
        """Target sample rate chosen in the selector."""
        data = self.sample_rate_cb.currentData()
        try:
            return int(data)
        except (TypeError, ValueError):
            return int(SP404_SPEC["recommended_sample_rate"])

    def update_footer_label(self):
        """Refresh the footer to show the current conversion target."""
        rate = self.selected_sample_rate() if hasattr(self, "sample_rate_cb") else int(
            SP404_SPEC["recommended_sample_rate"]
        )
        self.specs_label.setText(
            f"{rate} Hz | "
            f"{SP404_SPEC['bit_depth']}-bit | "
            f"{'Stereo' if SP404_SPEC['channels'] == 2 else 'Mono'} | "
            f"{SP404_SPEC['codec']} | .wav"
        )

    def start_conversion(self):
        """Start batch conversion."""
        if not self.pending_files:
            return

        self.convert_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.mirror_cb.setEnabled(False)
        self.sample_rate_cb.setEnabled(False)
        self.file_list.setEnabled(False)

        self.overall_progress.setRange(0, len(self.pending_files))
        self.overall_progress.setValue(0)
        self.status_label.setText("Starting...")

        preserve = self.mirror_cb.isChecked()
        target_rate = self.selected_sample_rate()

        # Submit workers to thread pool
        for i, (file_path, source_root) in enumerate(self.pending_files):
            worker = ConvertWorker(
                file_path,
                self.resolve_output_base(file_path, source_root, preserve),
                source_root,
                preserve,
                i + 1,
                len(self.pending_files),
                target_rate,
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
        mirrored inside the output as <pack>_sp (output/<pack>_sp/<subfolders>/...).
        Without an output folder: a <pack>_sp mirror is created next to the source.
        """
        if self.output_dir is not None:
            if preserve_structure and source_root is not None:
                return self.output_dir / f"{source_root.name}_sp"
            return self.output_dir
        if preserve_structure and source_root is not None:
            return source_root.parent / f"{source_root.name}_sp"
        return file_path.parent

    @Slot(ConversionResult)
    def on_file_finished(self, result: ConversionResult):
        """Handle single file conversion result."""
        if result.success:
            out_name = result.output_path.name if result.output_path else result.input_path.name
            self.status_label.setText(f"{result.input_path.name} -> {out_name}")
        else:
            self.status_label.setText(f"{result.input_path.name}: {result.error}")

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
        self.sample_rate_cb.setEnabled(True)
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
