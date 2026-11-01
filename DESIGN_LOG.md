# Design log

Every look the site has had, so an old one can be seen or brought back.

## v1: neon side panel (1 November 2026)

The roof's 3D view on the left and a 400px panel on the right, with a switch between Ember and Vega and a row of tabs
under each. It got a clean-up the same day: Inter for reading, quieter labels, one camera toolbar, needs and thoughts
moved into the panel.

- See it live: https://xyldz.github.io/ember/v1.html (a frozen copy, `site/v1.html`)
- In git: the tag `design-v1` (commit b6e4a9c)
- Bring it back: `git checkout design-v1 -- site/index.html`, then commit and push

## v2: full-screen roof (1 November 2026, current)

The roof fills the screen. Ember's and Vega's cards float top left (what they're doing, Ember's needs); tapping one opens
its story in a glass drawer on the right (a sheet from the bottom on phones), and the 3D camera re-centres in the space
left over. A toolbar along the bottom. Three looks, switched with 🎨: sleek neon, cosy lo-fi night, retro terminal, all
drawn from one set of colour and font tokens at the top of `site/index.html`.
