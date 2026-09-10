# Preparing the public beta

Target: GitHub **prerelease**, tag `v0.1.0-beta.1`, title
`TFT Coach 0.1.0-beta.1 — Windows beta`. Do not mark it as the stable/latest release.

Build and assemble on Windows from the repository root:

```powershell
npm run verify
npm run package
npm run test:packaged
npm run prepare:beta
```

`prepare:beta` creates `dist-electron/beta-0.1.0-beta.1/` with the installer,
release notes, tester guide, notices ZIP, build manifest, and SHA-256 checksums.
It refuses to overwrite an existing release directory. It does not publish,
create a tag, change the installed app, or send files externally.

Verify the assembled downloads:

```powershell
python scripts/prepare_beta.py --verify dist-electron/beta-0.1.0-beta.1
```

The notices collector records installed Python build-environment packages and
the JavaScript runtime packages, copies available license texts, and fingerprints
the locally supplied Tesseract files. It includes build-only packages
conservatively; it is not a completed binary dependency or redistribution audit.

For this candidate, `flatbuffers 25.12.19` and `PyGetWindow 0.0.9` have license
metadata but no copied license text in their installed wheels. The configured
package index did not provide a matching FlatBuffers source archive. Obtain and
verify the matching upstream notices before marking this review complete.

Before publication:

- Resolve the outstanding review items in `resources/notices/inventory.json`,
  including Tesseract DLL/traineddata notices and game-asset/cache provenance.
- Record clean-machine install, quit, upgrade, reinstall, uninstall, diagnostic
  export, and representative gameplay test results.
- Decide whether to proceed with the disclosed unsigned beta or arrange signing.
- Commit the release changes and build from that exact revision. The local
  candidate manifest records its base revision and whether local edits existed;
  it must not be represented as a clean tagged build.
- Create the prerelease from that revision, attach the prepared files, and use
  `BETA_RELEASE_NOTES.md` as the release body after updating its candidate status.

Do not upload the entire `dist-electron` directory, training data, local logs, or
the writable app-data directory. `latest.yml` is not an automatic-update channel.
Windows CI and automated, pinned Tesseract sourcing remain follow-up work.
