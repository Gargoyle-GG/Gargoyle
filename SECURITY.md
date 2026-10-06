# Security

Found a security problem in the Gargoyle addon or app? Please report it privately, through
this repository's **Security** tab ("Report a vulnerability"), not in a public issue. You'll
get an answer, and a fix goes out as a new release.

How releases are protected:

- Every release is built by GitHub from the code in this repository
  ([release.yml](.github/workflows/release.yml)), with its build tools pinned to exact,
  checksummed versions.
- The app only installs an addon update if every file matches a manifest signed with
  Gargoyle's release key ([signing.py](helper/signing.py)). That key is kept offline, never on
  GitHub, so even someone who got into GitHub couldn't push an addon update to players.
- The app never runs anything it downloads: a new version of the app itself is an installer
  you choose to run.
