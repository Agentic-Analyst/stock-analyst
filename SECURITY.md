# Dependency security decisions

## CVE-2026-81726 / GHSA-8mgp-746c-j5xp (NLTK)

Status: not affected in the current worker execution path; no fixed NLTK release is
available as of 2026-09-13.

The worker receives NLTK 3.10.3 transitively through `newspaper3k` 0.2.8. The
advisory applies when an application enables NLTK `pathsec` enforcement and lets
an untrusted workflow choose model import or export paths passed to these APIs:

- `TransitionParser.train` and `TransitionParser.parse`
- `AveragedPerceptron.save` and `AveragedPerceptron.load`
- `PerceptronTagger.save_to_json`
- `save_maxent_params`

The product does not enable NLTK `pathsec`, accept model-artifact paths, or call
any of those APIs. Its only `newspaper3k` operation is constructing an `Article`
from a URL and calling `download()` and `parse()`. Inspection of the installed
`newspaper3k` source shows that its NLTK use is limited to the Punkt tokenizer,
the ISRI stemmer, and `wordpunct_tokenize`.

`tests/test_dependency_vex.py` enforces this decision by scanning both product
source and the installed `newspaper3k` package for the affected API names. A
new direct or transitive call therefore fails CI and requires a fresh security
review.

Reopen this decision when any of the following occurs:

- NLTK or `newspaper3k` is upgraded or replaced.
- Product code begins using NLTK directly.
- NLTK `pathsec` is enabled.
- A user-controlled model import, export, or persistence path is introduced.
- A patched NLTK release becomes available; upgrade instead of retaining this
  exception.

Reference: <https://github.com/advisories/GHSA-8mgp-746c-j5xp>
