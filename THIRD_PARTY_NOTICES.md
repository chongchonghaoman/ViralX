# Third-party notices

## ShotLoom scene-detection adaptation

`shot_analyzers.py` adapts the dual-detector structure from
[Supreme-Ultimate/shotloom](https://github.com/Supreme-Ultimate/shotloom),
`backend/services/shot_detector.py`, commit
`78b65e24a587052ff2c0c4ccae72575295bde34f`. ShotLoom is distributed under the
MIT License. ViralX reimplemented only the local ContentDetector +
AdaptiveDetector orchestration and does not bundle ShotLoom's web application,
authentication, tasks, database, or recommendation prompts.

The ViralX adaptation deliberately differs from the referenced implementation:
it keeps genuine fast cuts and merges only detector-noise segments shorter than
80 ms, instead of discarding every segment shorter than 0.5 seconds.

## PySceneDetect and OpenCV

- PySceneDetect 0.6.4 is distributed under the BSD 3-Clause License.
- `opencv-python-headless` is distributed under the Apache License 2.0 and
  provides the OpenCV Python bindings used for keyframe sampling.

Their packages and license metadata are installed through `requirements.txt`;
ViralX does not claim ownership of either project.

## DNP Shuei Mincho title artwork

The homepage title SVGs contain finished glyph outlines generated locally from a user-supplied
`DNPShueiMinPr6N B` font file. ViralX does not claim ownership of the underlying typeface and
does not include, embed, convert, redistribute, or deploy that source font program. The outlined
title assets must not be treated as a source for reconstructing or distributing the typeface.
