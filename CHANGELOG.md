# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Repository skeleton, CI, and `CLAUDE.md` (Stage 0 items R1 and D1).
- Zigbee2MQTT backend (Phase 2A): pure protocol parsing driven by the Stage 0 G1
  capture, an adapter that reads the retained bridge topics and writes bindings,
  managed `dl_` groups for one-to-many rules, and curated profile entries for the
  Inovelli Blue VZM31-SN and VZM32-SN. The write path is modelled from the
  Zigbee2MQTT documentation and has never been performed against hardware
  (assumption A2, issue #6). The backend is built at config entry setup as of
  Phase 2A's last commit, over Home Assistant's own `mqtt` integration.
