# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

## What is signed

Only `KestrelDiskImager.exe`, built by the GitHub Actions workflow
[`.github/workflows/build.yml`](.github/workflows/build.yml) from a tagged commit
(`v*`) in this repository. Files built on a personal computer are never signed with
this certificate.

## Team roles

| Role | Members |
|---|---|
| Committers and reviewers | [Aydin Fatoglu](https://github.com/AydinFatoglu) |
| Approvers | [Aydin Fatoglu](https://github.com/AydinFatoglu) |

Every signing request must be approved by hand by an approver before it is signed.

## Privacy

This program will not send any information to other networked systems unless
the user specifically asks for it. It makes no network connections.

## Reporting

Report a wrongly signed file or a security issue as described in
[SECURITY.md](SECURITY.md).
