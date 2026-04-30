#!/bin/bash
# WARP Control GUI — Installer
set -e

echo "═══════════════════════════════════════"
echo "  WARP Control GUI — Installer"
echo "═══════════════════════════════════════"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "✗ Python 3 not found. Install it first."
    exit 1
fi

# Install PyQt6
echo "→ Installing PyQt6..."
pip3 install PyQt6 --quiet --break-system-packages 2>/dev/null || pip3 install PyQt6 --quiet

# Install to /opt
echo "→ Copying files to /opt/warp-gui..."
sudo mkdir -p /opt/warp-gui
sudo cp warp_gui.py /opt/warp-gui/

# Make executable
sudo chmod +x /opt/warp-gui/warp_gui.py

# Desktop entry
echo "→ Installing desktop entry..."
sed "s|/opt/warp-gui/warp_gui.py|/opt/warp-gui/warp_gui.py|" warp-control.desktop > /tmp/warp-control.desktop
sudo cp /tmp/warp-control.desktop /usr/share/applications/
sudo update-desktop-database /usr/share/applications/ 2>/dev/null || true

# CLI shortcut
echo "→ Creating 'warp-gui' command..."
echo '#!/bin/bash
python3 /opt/warp-gui/warp_gui.py "$@"' | sudo tee /usr/local/bin/warp-gui > /dev/null
sudo chmod +x /usr/local/bin/warp-gui

echo ""
echo "✓ WARP Control installed!"
echo "  Run:    warp-gui"
echo "  Or find 'WARP Control' in your app menu."
echo ""
