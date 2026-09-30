# LaTeX style provenance

`cvpr.sty` is unmodified from the [official CVPR author kit](https://github.com/cvpr-org/author-kit/blob/main/cvpr.sty), downloaded 2026-09-28.
The Stanford assignment's AI template links to this kit through Overleaf.
Original notices remain in the file. Standard TeX dependencies are not vendored.

The paper adds `\hfuzz=0pt\vfuzz=0pt` after loading the style so the build can
detect overfull boxes; this changes diagnostic tolerance, not layout.
