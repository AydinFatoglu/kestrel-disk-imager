# Security policy

Kestrel Disk Imager runs with administrator rights and writes directly to physical
disks, so issues that could make it write to the wrong disk are treated as
security issues.

## Reporting a vulnerability

Please report it privately through GitHub: open the **Security** tab of this
repository and choose **Report a vulnerability**. Do not open a public issue.

Include the Windows version, the disk type (SD reader, USB drive, …) and the
related part of `writer.log`. Remove any personal paths from the log first.

## Supported versions

Only the latest release receives fixes.
