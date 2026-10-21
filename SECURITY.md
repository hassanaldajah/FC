# Security policy

## Supported versions
Only the latest release on the [Releases page](https://github.com/hassanaldajah/FC/releases)
gets security fixes.

## Reporting a vulnerability
Please **do not** open a public issue. Use GitHub's private reporting instead:
**Security** tab → **Report a vulnerability**
([direct link](https://github.com/hassanaldajah/FC/security/advisories/new)).

Include what you did, what happened, and a sample file if one is needed to show it.
This is a one-person project, so replies are best effort, usually within a week.

## What FC does and does not do
- It never connects to the internet. Every tool runs on your own computer.
- It opens Office files with macros turned off, and refuses files that unpack to more than 2 GB
  (zip bombs) or inputs larger than 4 GB.
- It never overwrites your original file; results are new files in the folder you pick.
- It cannot unlock password-protected files without the password, and it never will.

## Checking a download
Every release exe has a `.sha256` checksum and a signed build-provenance attestation that proves
it was built by this repository's GitHub Actions from the tagged source. See
[Download and verify](README.md#download-and-verify) in the README.
