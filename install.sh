#!/bin/bash
# Set up the Go2 backpack stack on a Jetson from this repo.
# Safe to re-run: every step checks before changing anything.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Repo: $REPO"

# 1. ~/go2_ws and ~/dds point into the repo (the services and docs use those paths)
for name in go2_ws dds; do
    target="$HOME/$name"
    if [ -L "$target" ]; then
        echo "~/$name already a symlink -> $(readlink "$target")"
    elif [ -e "$target" ]; then
        echo "~/$name exists and is not a symlink; move it away first" >&2
        exit 1
    else
        ln -s "$REPO/$name" "$target"
        echo "Linked ~/$name -> $REPO/$name"
    fi
done
mkdir -p "$REPO/dds/logs"

# 2. Dependencies
source /opt/ros/humble/setup.bash
sudo apt-get update
sudo apt-get install -y ros-humble-rmw-cyclonedds-cpp ros-humble-domain-bridge \
    ros-humble-topic-tools python3-serial python3-rosdep
[ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || sudo rosdep init
rosdep update
rosdep install --from-paths "$REPO/go2_ws/src" --ignore-src -y || \
    echo "rosdep reported missing keys; check the output above"

# 3. Build
(cd "$REPO/go2_ws" && colcon build --symlink-install)

# 4. System files
sudo cp "$REPO/system/udev/99-witmotion-imu.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo cp "$REPO/system/sysctl/60-cyclonedds.conf" /etc/sysctl.d/
sudo sysctl -p /etc/sysctl.d/60-cyclonedds.conf
sudo usermod -aG dialout "$USER"

# 5. Shell environment
if ! grep -q "Go2 DDS split" "$HOME/.bashrc"; then
    cp "$HOME/.bashrc" "$HOME/.bashrc.bak.$(date +%F)"
    { echo; cat "$REPO/system/bashrc/go2_bashrc.sh"; } >> "$HOME/.bashrc"
    echo "Added the Go2 block to ~/.bashrc (backup saved)"
else
    echo "~/.bashrc already has the Go2 block"
fi

# 6. Services (user units, started at boot via linger)
mkdir -p "$HOME/.config/systemd/user"
cp "$REPO"/system/systemd/go2-*.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable go2-driver go2-bridge go2-camera go2-gps go2-imu
sudo loginctl enable-linger "$USER"

echo
echo "Done. Start now with:"
echo "  systemctl --user start go2-driver go2-bridge go2-camera go2-gps go2-imu"
echo "Log out and back in (or reboot) for the dialout group to apply."
