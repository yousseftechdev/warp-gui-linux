# WARP Control — Linux GUI for Cloudflare WARP

I use Cloudflare WARP a LOT because of how my school network is configured (I'm in a boarding school so I need the school wifi to work properly 😭), but I use Linux as a daily desktop driver, and Cloudflare WARP doesn't have an official GUI for linux other than the Zero Trust version which I'm too lazy to set up an account for, so I used warp-cli for a while which became annoying since I had to spam `warp-cli status` to see if I was connected yet, and I couldn't see my current mode, I had to guess or reset it, so I decided to create my own GUI in python.

**DISCLAIMER:** Since I started this project during my exams, I used Claude's help for a LOT of this app's functions, forgive me for vibe coding 😓, but don't worry, more human updates will come soon once I'm done with exams since this is full of bugs and incomplete features, even the README.md needs fixing.

A sleek, dark-themed desktop GUI for managing Cloudflare WARP on Linux — since the official client ships with no GUI.

## Screenshots
Dark terminal-inspired UI with sidebar navigation, animated status orb.
![screenshot](screenshots/1778416503.png)
![screenshot2](screenshots/1778416530.png)

## Requirements

- Python 3.8+
- PyQt6 (`pip install PyQt6`)
- `notify-send`
- `warp-cli` installed (from Cloudflare's official repo)

## Install

### 1. Clone the repo and cd into it
```bash
git clone https://github.com/yousseftechdev/warp-gui-linux
cd warp-gui-linux
```

### 2. Run the install script
```bash
chmod +x install.sh
./install.sh
```

### 3. Launch the app!
1. Either through the terminal with the command `warp-gui`
2. Or through your app launcher/menu, it will be called `WARP Control`

## Notes
- In tiling window managers such as Hyprland, the window will be tiled and stretched sometimes, so use this window rule in your config to stop it from tiling:
```hyprlang
# works on hyprland only, look up how to do it on i3
windowrule {
    name = untile-warp
    match:title = WARP Control
    float = true
    size = 700,600
}
```
- All other operations run as your normal user via `warp-cli`.
- Version 1.2 now has background activity supoprt!!
