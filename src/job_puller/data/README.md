# First-party ATS board registry

`boards.json` contains reusable ATS board routes observed and verified by this
project. It does not contain raw browser captures, LinkedIn URLs, job records,
personal inventory, or copied third-party seed datasets.

New installations enable this small registry by default. A workspace can set
`use_bundled_boards: false` to opt out. Explicit local board entries always
override bundled entries with the same provider and board ID.

Add a route only after a captured external application link identifies the ATS
provider and the board endpoint responds successfully. Keep unsupported career
sites in the private capture database until the scraper supports them.
