# License overrides

`victory-vendor@37.3.6` declares `MIT AND ISC` but its npm archive contains no
standalone license file. The override reproduces `LICENSE.txt` from Victory tag
`v37.3.6`, commit `d9d9ca2d5038d6ef9de91f2cef39e6fb2733baa6`:

<https://github.com/FormidableLabs/victory/blob/d9d9ca2d5038d6ef9de91f2cef39e6fb2733baa6/LICENSE.txt>

The package's vendored d3 dependencies are also present in the production lock
graph. Their ISC/BSD license texts are therefore included as their own entries
in the generated notice.
