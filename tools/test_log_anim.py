import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QPoint, QEventLoop

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import MainWindow

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow(start_minimized=True)
    w.move(100, 50)
    w.show()
    app.processEvents()

    # Wait for startup background IP thread to complete cleanly
    if hasattr(w, "ip_thread") and w.ip_thread:
        w.ip_thread.wait(3000)
    app.processEvents()

    # Track window height changes
    height_changes = 0
    current_height = w.height()

    orig_resize = w.resize
    def tracked_resize(*args):
        nonlocal height_changes, current_height
        if len(args) == 2:
            new_h = args[1]
        elif len(args) == 1:
            new_h = args[0].height()
        else:
            new_h = current_height
        if new_h != current_height:
            height_changes += 1
            current_height = new_h
        return orig_resize(*args)

    w.resize = tracked_resize

    # Sampler
    btn_y_samples = []
    top_card_y_samples = []

    def sample_positions():
        btn_pt = w.btn_toggle_log.mapToGlobal(QPoint(0, 0))
        card_pt = w.card_track.mapToGlobal(QPoint(0, 0))
        btn_y_samples.append(btn_pt.y())
        top_card_y_samples.append(card_pt.y())

    sampler_timer = QTimer()
    sampler_timer.setInterval(2)
    sampler_timer.timeout.connect(sample_positions)
    sampler_timer.start()

    CYCLES = 3
    for cycle in range(1, CYCLES + 1):
        print(f"\n--- Cycle {cycle} ---")
        cycle_initial_changes = height_changes
        btn_y_samples.clear()
        top_card_y_samples.clear()

        # 1. Expand
        print("Expanding log...", flush=True)
        w.toggle_log_view()
        print("Toggled log view (expanding)", flush=True)
        loop = QEventLoop()
        QTimer.singleShot(350, loop.quit)
        loop.exec()
        print(f"Expanded finished. Panel height: {w.reveal_panel.height()}, btn Y set: {set(btn_y_samples)}", flush=True)

        assert w._is_log_expanded, "Log should be expanded"
        assert w.reveal_panel.isVisible(), "RevealPanel should be visible"
        assert w.reveal_panel.height() == 240, f"RevealPanel height expected 240, got {w.reveal_panel.height()}"

        # 2. Collapse
        print("Collapsing log...", flush=True)
        w.toggle_log_view()
        print("Toggled log view (collapsing)", flush=True)
        loop = QEventLoop()
        QTimer.singleShot(350, loop.quit)
        loop.exec()
        print(f"Collapse finished. Panel height: {w.reveal_panel.height()}, btn Y set: {set(btn_y_samples)}", flush=True)

        assert not w._is_log_expanded, "Log should be collapsed"
        assert not w.reveal_panel.isVisible(), "RevealPanel should be hidden"
        assert w.reveal_panel.height() == 0, f"RevealPanel height expected 0, got {w.reveal_panel.height()}"

        cycle_changes = height_changes - cycle_initial_changes
        btn_spread = max(btn_y_samples) - min(btn_y_samples) if btn_y_samples else 0
        card_spread = max(top_card_y_samples) - min(top_card_y_samples) if top_card_y_samples else 0

        print(f"Cycle {cycle} Results:")
        print(f"  Samples collected: {len(btn_y_samples)}")
        print(f"  Button Y min: {min(btn_y_samples)}, max: {max(btn_y_samples)}, spread: {btn_spread} px")
        print(f"  Top Card Y min: {min(top_card_y_samples)}, max: {max(top_card_y_samples)}, spread: {card_spread} px")
        print(f"  Window height changes: {cycle_changes} (expected: 2)")

        assert btn_spread == 0, f"Button Y moved during animation! Spread was {btn_spread} px"
        assert card_spread == 0, f"Top card moved during animation! Spread was {card_spread} px"
        assert cycle_changes == 2, f"Window height should change exactly 2 times per cycle, changed {cycle_changes} times"

    sampler_timer.stop()
    print("\nALL CHECKS PASSED: 0 px spread, exactly 2 window height changes per cycle. PASS!", flush=True)
    w.close()
    return True

if __name__ == "__main__":
    import traceback
    try:
        success = run_test()
    except Exception as e:
        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
