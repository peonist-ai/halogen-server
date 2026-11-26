# halogen trademark policy

**Version 0.1 · 14 September 2026**

"halogen" and "Peonist" are trademarks of Peonist, LLC (the "Marks"). This
policy says how they may be used without asking. It applies whatever license
the software is under: an open-source license grants rights in the code, not
in the name (Apache 2.0 says so in as many words, in its section 6).

The point of the policy is narrow. When someone runs "halogen", they should
get the software Peonist built and gated, and when a number is published
under that name, it should be one this project stands behind.

## You may, without permission

1. **Refer to the project.** Say that your product, article, benchmark or
   talk is about halogen, runs on halogen, integrates with halogen, or is
   compatible with it. "Powered by halogen", "a halogen backend for
   Lemonade", "halogen recipe" are all fine.
2. **Redistribute official builds unmodified** under the name, including
   inside a larger distribution (an OS package, a model manager, a
   container registry), as long as the version and the source commit are
   stated and the notices files travel with it.
3. **Build from unmodified official source** and distribute the result
   under the name, stating the commit it was built from. Changing only
   build flags, target architecture, the bundled runtime, or packaging
   metadata does not make a build modified for this purpose.
4. **Fork the code** (where the license allows it) and describe the fork as
   "a fork of halogen", "based on halogen", or "derived from halogen".
5. **Use the name for community activity** that is not a product: user
   groups, meetups, tutorials, Discord channels, non-commercial
   discussion sites.

## You may not, without written permission

1. **Distribute a modified build under the name.** A build that changes the
   engine's code, kernels, defaults, or the front-end's behaviour must be
   given its own name. Descriptive references ("a fork of halogen") are
   fine; calling it "halogen" is not.
2. **Use the Marks as, or as part of, the name of another product,
   service, company, or project**, including "halogen-something" product
   names that a reasonable person would take to be ours.
3. **Imply endorsement, affiliation or sponsorship** by Peonist that does
   not exist.
4. **Register domain names, social-media handles, or package names**
   consisting of or containing the Marks.
5. **Sell merchandise** bearing the Marks.
6. **Use a logo** of the project other than as we publish it, or alter it.

## Distributors, in particular

A distributor (a Linux distribution, AMD's Lemonade, a container registry,
a model manager) that builds halogen from a pinned official commit and
bundles a runtime with it is covered by "You may" item 3. We ask that the
distribution name the commit and version somewhere a user can find them,
and that bug reports that turn out to be packaging go to the distributor.

## Publishing numbers

Benchmarks on halogen are expressly permitted (the license says so too). If
you publish a number, please say the version, the hardware, the model, the
quantization, the context depth, and whether the tuning file and the
speculative drafter were on; the README states the conditions we use.

## Asking

Questions and permission requests: **trademarks@peonist.ai**. We say yes to
most things that do not confuse users about what they are running.

This policy may be updated; the version at the top identifies it.
