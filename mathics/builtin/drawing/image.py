# -*- coding: utf-8 -*-
"""
Image[] and image-related functions

Note that you (currently) need scikit-image installed in order for this \
module to work.
"""

# This tells documentation how to sort this module
# Here, we are also hiding "drawing" since this erroneously appears at
# the top level.
sort_order = "mathics.builtin.image-and-image-related-functions"

import base64
import functools
import math
import os.path as osp
from collections import defaultdict
from copy import deepcopy
from typing import Tuple

from mathics.builtin.base import AtomBuiltin, Builtin, String, Test
from mathics.builtin.box.image import ImageBox
from mathics.builtin.colors.color_internals import (
    colorspaces as known_colorspaces,
    convert_color,
)
from mathics.core.atoms import (
    Atom,
    Integer,
    Integer0,
    Integer1,
    MachineReal,
    Rational,
    Real,
)
from mathics.core.convert.expression import to_mathics_list
from mathics.core.convert.python import from_python
from mathics.core.evaluation import Evaluation
from mathics.core.expression import Expression
from mathics.core.list import ListExpression
from mathics.core.symbols import Symbol, SymbolDivide, SymbolNull, SymbolTrue
from mathics.core.systemsymbols import SymbolImage, SymbolRule
from mathics.eval.image import (
    convolve,
    extract_exif,
    get_image_size_spec,
    matrix_to_numpy,
    numpy_flip,
    numpy_to_matrix,
    pixels_as_float,
    pixels_as_ubyte,
    pixels_as_uint,
    resize_width_height,
)

SymbolColorQuantize = Symbol("ColorQuantize")
SymbolImage = Symbol("Image")
SymbolMatrixQ = Symbol("MatrixQ")
SymbolThreshold = Symbol("Threshold")

# Note a list of packages that are needed for image Builtins.
_image_requires = ("numpy", "PIL")
_skimage_requires = _image_requires + ("skimage", "scipy", "matplotlib", "networkx")

try:
    import warnings

    import numpy
    import PIL
    import PIL.ImageEnhance
    import PIL.ImageFilter
    import PIL.ImageOps

except ImportError:
    pass


try:
    import skimage.filters
except ImportError:
    have_skimage_filters = False
else:
    have_skimage_filters = True

from io import BytesIO

# The following classes are used to allow inclusion of
# Builtin Functions only when certain Python packages
# are available. They do this by setting the `requires` class variable.


class _ImageBuiltin(Builtin):
    requires = _image_requires


class _ImageTest(Test):
    """
    Testing Image Builtins -- those function names ending with "Q" -- that require scikit-image.
    """

    requires = _image_requires


class _SkimageBuiltin(_ImageBuiltin):
    """
    Image Builtins that require scikit-image.
    """

    requires = _skimage_requires


# Code related to Mathics Functions that import and export.


class ImageExport(_ImageBuiltin):
    """
    <dl>
      <dt> 'ImageExport["path", $image$]'
      <dd> export $image$ as file in "path".
    </dl>
    """

    no_doc = True

    messages = {"noimage": "only an Image[] can be exported into an image file"}

    def eval(self, path: String, expr, opts, evaluation: Evaluation):
        """ImageExport[path_String, expr_, opts___]"""
        if isinstance(expr, Image):
            expr.pil().save(path.value)
            return SymbolNull
        else:
            return evaluation.message("ImageExport", "noimage")


class ImageImport(_ImageBuiltin):
    """
    <dl>
      <dt> 'ImageImport["path"]'
      <dd> import an image from the file "path".
    </dl>

    ## Image
    >> Import["ExampleData/Einstein.jpg"]
     = -Image-
    >> Import["ExampleData/sunflowers.jpg"]
     = -Image-
    >> Import["ExampleData/MadTeaParty.gif"]
     = -Image-
    >> Import["ExampleData/moon.tif"]
     = -Image-
    >> Import["ExampleData/lena.tif"]
     = -Image-
    """

    no_doc = True

    def eval(self, path: String, evaluation: Evaluation):
        """ImageImport[path_String]"""
        pillow = PIL.Image.open(path.value)
        pixels = numpy.asarray(pillow)
        is_rgb = len(pixels.shape) >= 3 and pixels.shape[2] >= 3
        options_from_exif = extract_exif(pillow, evaluation)

        image = Image(pixels, "RGB" if is_rgb else "Grayscale", pillow=pillow)
        image_list_expression = [
            Expression(SymbolRule, String("Image"), image),
            Expression(SymbolRule, String("ColorSpace"), String(image.color_space)),
        ]

        if options_from_exif is not None:
            image_list_expression.append(options_from_exif)

        return ListExpression(*image_list_expression)


class _ImageArithmetic(_ImageBuiltin):
    messages = {"bddarg": "Expecting a number, image, or graphics instead of `1`."}

    @staticmethod
    def convert_Image(image):
        assert isinstance(image, Image)
        return pixels_as_float(image.pixels)

    @staticmethod
    def convert_args(*args):
        images = []
        for arg in args:
            if isinstance(arg, Image):
                images.append(_ImageArithmetic.convert_Image(arg))
            elif isinstance(arg, (Integer, Rational, Real)):
                images.append(float(arg.to_python()))
            else:
                return None, arg
        return images, None

    @staticmethod
    def _reduce(iterable, ufunc):
        result = None
        for i in iterable:
            if result is None:
                # ufunc is destructive so copy first
                result = numpy.copy(i)
            else:
                # e.g. result *= i
                ufunc(result, i, result)
        return result

    def eval(self, image, args, evaluation: Evaluation):
        "%(name)s[image_Image, args__]"
        images, arg = self.convert_args(image, *args.get_sequence())
        if images is None:
            return evaluation.message(self.get_name(), "bddarg", arg)
        ufunc = getattr(numpy, self.get_name(True)[5:].lower())
        result = self._reduce(images, ufunc).clip(0, 1)
        return Image(result, image.color_space)


class ImageAdd(_ImageArithmetic):
    """
    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageAdd.html</url>

    <dl>
      <dt>'ImageAdd[$image$, $expr_1$, $expr_2$, ...]'
      <dd>adds all $expr_i$ to $image$ where each $expr_i$ must be an image \
          or a real number.
    </dl>

    >> i = Image[{{0, 0.5, 0.2, 0.1, 0.9}, {1.0, 0.1, 0.3, 0.8, 0.6}}];

    >> ImageAdd[i, 0.5]
     = -Image-

    >> ImageAdd[i, i]
     = -Image-

    #> ImageAdd[i, 0.2, i, 0.1]
     = -Image-

    #> ImageAdd[i, x]
     : Expecting a number, image, or graphics instead of x.
     = ImageAdd[-Image-, x]

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> noise = RandomImage[{-0.1, 0.1}, ImageDimensions[ein]];
    >> ImageAdd[noise, ein]
     = -Image-

    >> lena = Import["ExampleData/lena.tif"];
    >> noise = RandomImage[{-0.2, 0.2}, ImageDimensions[lena], ColorSpace -> "RGB"];
    >> ImageAdd[noise, lena]
     = -Image-
    """

    summary_text = "build an image adding pixel values of another image "


class ImageMultiply(_ImageArithmetic):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ImageMultiply.html</url>

    <dl>
      <dt>'ImageMultiply[$image$, $expr_1$, $expr_2$, ...]'
      <dd>multiplies all $expr_i$ with $image$ where each $expr_i$ must be an image or a real number.
    </dl>

    >> i = Image[{{0, 0.5, 0.2, 0.1, 0.9}, {1.0, 0.1, 0.3, 0.8, 0.6}}];

    >> ImageMultiply[i, 0.2]
     = -Image-

    >> ImageMultiply[i, i]
     = -Image-

    #> ImageMultiply[i, 0.2, i, 0.1]
     = -Image-

    #> ImageMultiply[i, x]
     : Expecting a number, image, or graphics instead of x.
     = ImageMultiply[-Image-, x]

    S> ein = Import["ExampleData/Einstein.jpg"];
    S> noise = RandomImage[{0.7, 1.3}, ImageDimensions[ein]];
    S> ImageMultiply[noise, ein]
     = -Image-
    """

    summary_text = "build an image multiplying the pixel values of another image "


class ImageSubtract(_ImageArithmetic):
    """
    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageSubtract.html</url>

    <dl>
      <dt>'ImageSubtract[$image$, $expr_1$, $expr_2$, ...]'
      <dd>subtracts all $expr_i$ from $image$ where each $expr_i$ must be an \
          image or a real number.
    </dl>

    >> i = Image[{{0, 0.5, 0.2, 0.1, 0.9}, {1.0, 0.1, 0.3, 0.8, 0.6}}];

    >> ImageSubtract[i, 0.2]
     = -Image-

    >> ImageSubtract[i, i]
     = -Image-

    #> ImageSubtract[i, 0.2, i, 0.1]
     = -Image-

    #> ImageSubtract[i, x]
     : Expecting a number, image, or graphics instead of x.
     = ImageSubtract[-Image-, x]
    """

    summary_text = "build an image substracting pixel values of another image "


class RandomImage(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/RandomImage.html</url>

    <dl>
    <dt>'RandomImage[$max$]'
      <dd>creates an image of random pixels with values 0 to $max$.
    <dt>'RandomImage[{$min$, $max$}]'
      <dd>creates an image of random pixels with values $min$ to $max$.
    <dt>'RandomImage[..., $size$]'
      <dd>creates an image of the given $size$.
    </dl>

    >> RandomImage[1, {100, 100}]
     = -Image-

    #> RandomImage[0.5]
     = -Image-
    #> RandomImage[{0.1, 0.9}]
     = -Image-
    #> RandomImage[0.9, {400, 600}]
     = -Image-
    #> RandomImage[{0.1, 0.5}, {400, 600}]
     = -Image-

    #> RandomImage[{0.1, 0.5}, {400, 600}, ColorSpace -> "RGB"]
     = -Image-
    """

    options = {"ColorSpace": "Automatic"}

    messages = {
        "bddim": "The specified dimension `1` should be a pair of positive integers.",
        "imgcstype": "`1` is an invalid color space specification.",
    }
    rules = {
        "RandomImage[]": "RandomImage[{0, 1}, {150, 150}]",
        "RandomImage[max_?RealNumberQ]": "RandomImage[{0, max}, {150, 150}]",
        "RandomImage[{minval_?RealNumberQ, maxval_?RealNumberQ}]": "RandomImage[{minval, maxval}, {150, 150}]",
        "RandomImage[max_?RealNumberQ, {w_Integer, h_Integer}]": "RandomImage[{0, max}, {w, h}]",
    }
    summary_text = "build an image with random pixels"

    def eval(self, minval, maxval, w, h, evaluation, options):
        "RandomImage[{minval_?RealNumberQ, maxval_?RealNumberQ}, {w_Integer, h_Integer}, OptionsPattern[RandomImage]]"
        color_space = self.get_option(options, "ColorSpace", evaluation)
        if (
            isinstance(color_space, Symbol)
            and color_space.get_name() == "System`Automatic"
        ):
            cs = "Grayscale"
        else:
            cs = color_space.get_string_value()
        size = [w.value, h.value]
        if size[0] <= 0 or size[1] <= 0:
            return evaluation.message("RandomImage", "bddim", from_python(size))
        minrange, maxrange = minval.round_to_float(), maxval.round_to_float()

        if cs == "Grayscale":
            data = (
                numpy.random.rand(size[1], size[0]) * (maxrange - minrange) + minrange
            )
        elif cs == "RGB":
            data = (
                numpy.random.rand(size[1], size[0], 3) * (maxrange - minrange)
                + minrange
            )
        else:
            return evaluation.message("RandomImage", "imgcstype", color_space)
        return Image(data, cs)


class ImageResize(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ImageResize.html</url>

    <dl>
      <dt>'ImageResize[$image$, $width$]'
      <dd>

      <dt>'ImageResize[$image$, {$width$, $height$}]'
      <dd>
    </dl>

    The Resampling option can be used to specify how to resample the image. Options are:
    <ul>
      <li>Automatic
      <li>Bicubic
      <li>Bilinear
      <li>Box
      <li>Hamming
      <li>Lanczos
      <li>Nearest
    </ul>

    See <url>
    :Pillow Filters:
    https://pillow.readthedocs.io/en/stable/handbook/concepts.html#filters</url>\
    for a description of these.

    S> alice = Import["ExampleData/MadTeaParty.gif"]
     = -Image-

    S> shape = ImageDimensions[alice]
     = {640, 487}

    S> ImageResize[alice, shape / 2]
     = -Image-

    The default sampling method is "Bicubic" which has pretty good upscaling \
    and downscaling quality. However "Box" is the fastest:


    S> ImageResize[alice, shape / 2, Resampling -> "Box"]
     = -Image-
    """

    messages = {
        "imgrssz": "The size `1` is not a valid image size specification.",
        "imgrsm": "Invalid resampling method `1`.",
        "gaussaspect": "Gaussian resampling needs to maintain aspect ratio.",
        "skimage": "Please install scikit-image to use Resampling -> Gaussian.",
    }

    options = {"Resampling": "Automatic"}
    summary_text = "resize an image"

    def eval_resize_width(self, image, s, evaluation, options):
        "ImageResize[image_Image, s_, OptionsPattern[ImageResize]]"
        old_w = image.pixels.shape[1]
        if s.has_form("List", 1):
            width = s.elements[0]
        else:
            width = s
        w = get_image_size_spec(old_w, width)
        if w is None:
            return evaluation.message("ImageResize", "imgrssz", s)
        if s.has_form("List", 1):
            height = width
        else:
            height = Symbol("Automatic")
        return self.eval_resize_width_height(image, width, height, evaluation, options)

    def eval_resize_width_height(self, image, width, height, evaluation, options):
        "ImageResize[image_Image, {width_, height_}, OptionsPattern[ImageResize]]"
        # resampling method
        resampling = self.get_option(options, "Resampling", evaluation)
        if (
            isinstance(resampling, Symbol)
            and resampling.get_name() == "System`Automatic"
        ):
            resampling_name = "Bicubic"
        else:
            resampling_name = resampling.value

        # find new size
        old_w, old_h = image.pixels.shape[1], image.pixels.shape[0]
        w = get_image_size_spec(old_w, width)
        h = get_image_size_spec(old_h, height)
        if h is None or w is None:
            return evaluation.message(
                "ImageResize", "imgrssz", to_mathics_list(width, height)
            )

        # handle Automatic
        old_aspect_ratio = old_w / old_h
        if w == 0 and h == 0:
            # if both width and height are Automatic then use old values
            w, h = old_w, old_h
        elif w == 0:
            w = max(1, h * old_aspect_ratio)
        elif h == 0:
            h = max(1, w / old_aspect_ratio)

        if resampling_name != "Gaussian":
            # Gaussian need to unrounded values to compute scaling ratios.
            # round to closest pixel for other methods.
            h, w = int(round(h)), int(round(w))

        # perform the resize
        return resize_width_height(image, w, h, resampling_name, evaluation)


class ImageReflect(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ImageReflect.html</url>
    <dl>
      <dt>'ImageReflect[$image$]'
      <dd>Flips $image$ top to bottom.

      <dt>'ImageReflect[$image$, $side$]'
      <dd>Flips $image$ so that $side$ is interchanged with its opposite.

      <dt>'ImageReflect[$image$, $side_1$ -> $side_2$]'
      <dd>Flips $image$ so that $side_1$ is interchanged with $side_2$.
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> ImageReflect[ein]
     = -Image-
    >> ImageReflect[ein, Left]
     = -Image-
    >> ImageReflect[ein, Left -> Top]
     = -Image-

    #> ein == ImageReflect[ein, Left -> Left] == ImageReflect[ein, Right -> Right] == ImageReflect[ein, Top -> Top] == ImageReflect[ein, Bottom -> Bottom]
     = True
    #> ImageReflect[ein, Left -> Right] == ImageReflect[ein, Right -> Left] == ImageReflect[ein, Left] == ImageReflect[ein, Right]
     = True
    #> ImageReflect[ein, Bottom -> Top] == ImageReflect[ein, Top -> Bottom] == ImageReflect[ein, Top] == ImageReflect[ein, Bottom]
     = True
    #> ImageReflect[ein, Left -> Top] == ImageReflect[ein, Right -> Bottom]     (* Transpose *)
     = True
    #> ImageReflect[ein, Left -> Bottom] == ImageReflect[ein, Right -> Top]     (* Anti-Transpose *)
     = True

    #> ImageReflect[ein, x -> Top]
     : x -> Top is not a valid 2D reflection specification.
     = ImageReflect[-Image-, x -> Top]
    """

    summary_text = "reflect an image"
    rules = {
        "ImageReflect[image_Image]": "ImageReflect[image, Top -> Bottom]",
        "ImageReflect[image_Image, Top|Bottom]": "ImageReflect[image, Top -> Bottom]",
        "ImageReflect[image_Image, Left|Right]": "ImageReflect[image, Left -> Right]",
    }

    messages = {"bdrfl2": "`1` is not a valid 2D reflection specification."}

    def eval(self, image, orig, dest, evaluation: Evaluation):
        "ImageReflect[image_Image, Rule[orig_, dest_]]"
        if isinstance(orig, Symbol) and isinstance(dest, Symbol):
            specs = [orig.get_name(), dest.get_name()]
            specs.sort()  # `Top -> Bottom` is the same as `Bottom -> Top`

        def anti_transpose(i):
            return numpy.flipud(numpy.transpose(numpy.flipud(i)))

        def no_op(i):
            return i

        method = {
            ("System`Bottom", "System`Top"): numpy.flipud,
            ("System`Left", "System`Right"): numpy.fliplr,
            ("System`Left", "System`Top"): numpy.transpose,
            ("System`Right", "System`Top"): anti_transpose,
            ("System`Bottom", "System`Left"): anti_transpose,
            ("System`Bottom", "System`Right"): numpy.transpose,
            ("System`Bottom", "System`Bottom"): no_op,
            ("System`Top", "System`Top"): no_op,
            ("System`Left", "System`Left"): no_op,
            ("System`Right", "System`Right"): no_op,
        }.get(tuple(specs), None)

        if method is None:
            return evaluation.message(
                "ImageReflect", "bdrfl2", Expression(SymbolRule, orig, dest)
            )

        return Image(method(image.pixels), image.color_space)


class ImageRotate(_ImageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/ImageRotate.html</url>

    <dl>
    <dt>'ImageRotate[$image$]'
      <dd>Rotates $image$ 90 degrees counterclockwise.
    <dt>'ImageRotate[$image$, $theta$]'
      <dd>Rotates $image$ by a given angle $theta$
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];

    >> ImageRotate[ein]
     = -Image-

    >> ImageRotate[ein, 45 Degree]
     = -Image-

    >> ImageRotate[ein, Pi / 4]
     = -Image-

    #> ImageRotate[ein, ein]
     : Angle -Image- should be a real number, one of Top, Bottom, Left, Right, or a rule from one to another.
     = ImageRotate[-Image-, -Image-]
    """

    messages = {
        "imgang": "Angle `1` should be a real number, one of Top, Bottom, Left, Right, or a rule from one to another."
    }

    rules = {"ImageRotate[i_Image]": "ImageRotate[i, 90 Degree]"}

    summary_text = "rotate an image"

    def eval(self, image, angle, evaluation: Evaluation):
        "ImageRotate[image_Image, angle_]"

        # FIXME: this test I suppose is okay in that it checks more or less what is needed.
        # However there might be a better test like for Real-valued-ness which could be used
        # instead.
        py_angle = (
            angle.round_to_float(evaluation)
            if hasattr(angle, "round_to_float")
            else None
        )

        if py_angle is None:
            return evaluation.message("ImageRotate", "imgang", angle)

        def rotate(im):
            return im.rotate(
                180 * py_angle / math.pi, resample=PIL.Image.BICUBIC, expand=True
            )

        return image.filter(rotate)


class ImagePartition(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ImagePartition.html</url>

    <dl>
      <dt>'ImagePartition[$image$, $s$]'
      <dd>Partitions an image into an array of $s$ x $s$ pixel subimages.

      <dt>'ImagePartition[$image$, {$w$, $h$}]'
      <dd>Partitions an image into an array of $w$ x $h$ pixel subimages.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> ImageDimensions[lena]
     = {512, 512}
    >> ImagePartition[lena, 256]
     = {{-Image-, -Image-}, {-Image-, -Image-}}

    >> ImagePartition[lena, {512, 128}]
     = {{-Image-}, {-Image-}, {-Image-}, {-Image-}}

    #> ImagePartition[lena, 257]
     = {{-Image-}}
    #> ImagePartition[lena, 512]
     = {{-Image-}}
    #> ImagePartition[lena, 513]
     = {}
    #> ImagePartition[lena, {256, 300}]
     = {{-Image-, -Image-}}

    #> ImagePartition[lena, {0, 300}]
     : {0, 300} is not a valid size specification for image partitions.
     = ImagePartition[-Image-, {0, 300}]
    """

    summary_text = "divide an image in an array of sub-images"
    rules = {"ImagePartition[i_Image, s_Integer]": "ImagePartition[i, {s, s}]"}

    messages = {"arg2": "`1` is not a valid size specification for image partitions."}

    def eval(self, image, w: Integer, h: Integer, evaluation: Evaluation):
        "ImagePartition[image_Image, {w_Integer, h_Integer}]"
        py_w = w.value
        py_h = h.value
        if py_w <= 0 or py_h <= 0:
            return evaluation.message("ImagePartition", "arg2", ListExpression(w, h))
        pixels = image.pixels
        shape = pixels.shape

        # drop blocks less than w x h
        parts = []
        for yi in range(shape[0] // py_h):
            row = []
            for xi in range(shape[1] // py_w):
                p = pixels[yi * py_h : (yi + 1) * py_h, xi * py_w : (xi + 1) * py_w]
                row.append(Image(p, image.color_space))
            if row:
                parts.append(row)
        return from_python(parts)


class ImageAdjust(_ImageBuiltin):
    """

    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageAdjust.html</url>

    <dl>
      <dt>'ImageAdjust[$image$]'
      <dd>adjusts the levels in $image$.

      <dt>'ImageAdjust[$image$, $c$]'
      <dd>adjusts the contrast in $image$ by $c$.

      <dt>'ImageAdjust[$image$, {$c$, $b$}]'
      <dd>adjusts the contrast $c$, and brightness $b$ in $image$.

      <dt>'ImageAdjust[$image$, {$c$, $b$, $g$}]'
      <dd>adjusts the contrast $c$, brightness $b$, and gamma $g$ in $image$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> ImageAdjust[lena]
     = -Image-
    """

    summary_text = "adjust levels, brightness, contrast, gamma, etc"
    rules = {
        "ImageAdjust[image_Image, c_?RealNumberQ]": "ImageAdjust[image, {c, 0, 1}]",
        "ImageAdjust[image_Image, {c_?RealNumberQ, b_?RealNumberQ}]": "ImageAdjust[image, {c, b, 1}]",
    }

    def eval_auto(self, image, evaluation: Evaluation):
        "ImageAdjust[image_Image]"
        pixels = pixels_as_float(image.pixels)

        # channel limits
        axis = (0, 1)
        cmaxs, cmins = pixels.max(axis=axis), pixels.min(axis=axis)

        # normalise channels
        scales = cmaxs - cmins
        if not scales.shape:
            scales = numpy.array([scales])
        scales[scales == 0.0] = 1
        pixels -= cmins
        pixels /= scales
        return Image(pixels, image.color_space)

    def eval_contrast_brightness_gamma(self, image, c, b, g, evaluation: Evaluation):
        "ImageAdjust[image_Image, {c_?RealNumberQ, b_?RealNumberQ, g_?RealNumberQ}]"

        im = image.pil()

        # gamma
        g = g.round_to_float()
        if g != 1:
            im = PIL.ImageEnhance.Color(im).enhance(g)

        # brightness
        b = b.round_to_float()
        if b != 0:
            im = PIL.ImageEnhance.Brightness(im).enhance(b + 1)

        # contrast
        c = c.round_to_float()
        if c != 0:
            im = PIL.ImageEnhance.Contrast(im).enhance(c + 1)

        return Image(numpy.array(im), image.color_space)


class Blur(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Blur.html</url>

    <dl>
      <dt>'Blur[$image$]'
      <dd>gives a blurred version of $image$.

      <dt>'Blur[$image$, $r$]'
      <dd>blurs $image$ with a kernel of size $r$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> Blur[lena]
     = -Image-
    >> Blur[lena, 5]
     = -Image-
    """

    summary_text = "blur an image"
    rules = {
        "Blur[image_Image]": "Blur[image, 2]",
        "Blur[image_Image, r_?RealNumberQ]": "ImageConvolve[image, BoxMatrix[r] / Total[Flatten[BoxMatrix[r]]]]",
    }


class Sharpen(_ImageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/Sharpen.html</url>

    <dl>
      <dt>'Sharpen[$image$]'
      <dd>gives a sharpened version of $image$.

      <dt>'Sharpen[$image$, $r$]'
      <dd>sharpens $image$ with a kernel of size $r$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> Sharpen[lena]
     = -Image-
    >> Sharpen[lena, 5]
     = -Image-
    """

    summary_text = "sharpen version of an image"
    rules = {"Sharpen[i_Image]": "Sharpen[i, 2]"}

    def eval(self, image, r, evaluation: Evaluation):
        "Sharpen[image_Image, r_?RealNumberQ]"
        f = PIL.ImageFilter.UnsharpMask(r.round_to_float())
        return image.filter(lambda im: im.filter(f))


class GaussianFilter(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/GaussianFilter.html</url>

    <dl>
      <dt>'GaussianFilter[$image$, $r$]'
      <dd>blurs $image$ using a Gaussian blur filter of radius $r$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> GaussianFilter[lena, 2.5]
     = -Image-
    """

    summary_text = "apply a gaussian filter to an image"
    messages = {"only3": "GaussianFilter only supports up to three channels."}

    def eval_radius(self, image, radius, evaluation: Evaluation):
        "GaussianFilter[image_Image, radius_?RealNumberQ]"
        if len(image.pixels.shape) > 2 and image.pixels.shape[2] > 3:
            return evaluation.message("GaussianFilter", "only3")
        else:
            f = PIL.ImageFilter.GaussianBlur(radius.round_to_float())
            return image.filter(lambda im: im.filter(f))


# morphological image filters


class PillowImageFilter(_ImageBuiltin):
    """

    ## <url>:PillowImageFilter:</url>

    <dl>
      <dt>'PillowImageFilter[$image$, "filtername"]'
      <dd> applies an image filter "filtername" from the pillow library.
    </dl>
    TODO: test cases?
    """

    summary_text = "apply a pillow filter to an image"

    def compute(self, image, f):
        return image.filter(lambda im: im.filter(f))


class MinFilter(PillowImageFilter):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/MinFilter.html</url>

    <dl>
    <dt>'MinFilter[$image$, $r$]'
      <dd>gives $image$ with a minimum filter of radius $r$ applied on it. This always
      picks the smallest value in the filter's area.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> MinFilter[lena, 5]
     = -Image-
    """

    summary_text = "replace every pixel value by the minimum in a neighbourhood"

    def eval(self, image, r: Integer, evaluation: Evaluation):
        "MinFilter[image_Image, r_Integer]"
        return self.compute(image, PIL.ImageFilter.MinFilter(1 + 2 * r.value))


class MaxFilter(PillowImageFilter):
    """

    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/MaxFilter.html</url>

    <dl>
      <dt>'MaxFilter[$image$, $r$]'
      <dd>gives $image$ with a maximum filter of radius $r$ applied on it. This always \
          picks the largest value in the filter's area.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> MaxFilter[lena, 5]
     = -Image-
    """

    summary_text = "replace every pixel value by the maximum in a neighbourhood"

    def eval(self, image, r: Integer, evaluation: Evaluation):
        "MaxFilter[image_Image, r_Integer]"
        return self.compute(image, PIL.ImageFilter.MaxFilter(1 + 2 * r.value))


class MedianFilter(PillowImageFilter):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/MedianFilter.html</url>

    <dl>
      <dt>'MedianFilter[$image$, $r$]'
      <dd>gives $image$ with a median filter of radius $r$ applied on it. This always \
          picks the median value in the filter's area.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> MedianFilter[lena, 5]
     = -Image-
    """

    summary_text = "replace every pixel value by the median in a neighbourhood"

    def eval(self, image, r: Integer, evaluation: Evaluation):
        "MedianFilter[image_Image, r_Integer]"
        return self.compute(image, PIL.ImageFilter.MedianFilter(1 + 2 * r.value))


class EdgeDetect(_SkimageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/EdgeDetect.html</url>

    <dl>
      <dt>'EdgeDetect[$image$]'
      <dd>returns an image showing the edges in $image$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> EdgeDetect[lena]
     = -Image-
    >> EdgeDetect[lena, 5]
     = -Image-
    >> EdgeDetect[lena, 4, 0.5]
     = -Image-
    """

    summary_text = "detect edges in an image using Canny and other methods"
    rules = {
        "EdgeDetect[i_Image]": "EdgeDetect[i, 2, 0.2]",
        "EdgeDetect[i_Image, r_?RealNumberQ]": "EdgeDetect[i, r, 0.2]",
    }

    def eval(self, image, r, t, evaluation: Evaluation):
        "EdgeDetect[image_Image, r_?RealNumberQ, t_?RealNumberQ]"
        import skimage.feature

        pixels = image.grayscale().pixels
        return Image(
            skimage.feature.canny(
                pixels.reshape(pixels.shape[:2]),
                sigma=r.round_to_float() / 2,
                low_threshold=0.5 * t.round_to_float(),
                high_threshold=t.round_to_float(),
            ),
            "Grayscale",
        )


def _matrix(rows):
    return ListExpression(*[ListExpression(*r) for r in rows])


class BoxMatrix(_ImageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/BoxMatrix.html</url>

    <dl>
    <dt>'BoxMatrix[$s]'
      <dd>Gives a box shaped kernel of size 2 $s$ + 1.
    </dl>

    >> BoxMatrix[3]
     = {{1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}}
    """

    summary_text = "create a matrix with all its entries set to 1"

    def eval(self, r, evaluation: Evaluation):
        "BoxMatrix[r_?RealNumberQ]"
        py_r = abs(r.round_to_float())
        s = int(math.floor(1 + 2 * py_r))
        return _matrix([[Integer1] * s] * s)


class DiskMatrix(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/DiskMatrix.html</url>

    <dl>
      <dt>'DiskMatrix[$s]'
      <dd>Gives a disk shaped kernel of size 2 $s$ + 1.
    </dl>

    >> DiskMatrix[3]
     = {{0, 0, 1, 1, 1, 0, 0}, {0, 1, 1, 1, 1, 1, 0}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {1, 1, 1, 1, 1, 1, 1}, {0, 1, 1, 1, 1, 1, 0}, {0, 0, 1, 1, 1, 0, 0}}
    """

    summary_text = "create a matrix with 1 in a disk-shaped region, and 0 outside"

    def eval(self, r, evaluation: Evaluation):
        "DiskMatrix[r_?RealNumberQ]"
        py_r = abs(r.round_to_float())
        s = int(math.floor(0.5 + py_r))

        m = (Integer0, Integer1)
        r_sqr = (py_r + 0.5) * (py_r + 0.5)

        def rows():
            for y in range(-s, s + 1):
                yield [m[int((x) * (x) + (y) * (y) <= r_sqr)] for x in range(-s, s + 1)]

        return _matrix(rows())


class DiamondMatrix(_ImageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/DiamondMatrix.html</url>

    <dl>
    <dt>'DiamondMatrix[$s]'
      <dd>Gives a diamond shaped kernel of size 2 $s$ + 1.
    </dl>

    >> DiamondMatrix[3]
     = {{0, 0, 0, 1, 0, 0, 0}, {0, 0, 1, 1, 1, 0, 0}, {0, 1, 1, 1, 1, 1, 0}, {1, 1, 1, 1, 1, 1, 1}, {0, 1, 1, 1, 1, 1, 0}, {0, 0, 1, 1, 1, 0, 0}, {0, 0, 0, 1, 0, 0, 0}}
    """

    summary_text = "create a matrix with 1 in a diamond-shaped region, and 0 outside"

    def eval(self, r, evaluation: Evaluation):
        "DiamondMatrix[r_?RealNumberQ]"
        py_r = abs(r.round_to_float())
        t = int(math.floor(0.5 + py_r))

        zero = Integer0
        one = Integer1

        def rows():
            for d in range(0, t):
                p = [zero] * (t - d)
                yield p + ([one] * (1 + d * 2)) + p

            yield [one] * (2 * t + 1)

            for d in reversed(range(0, t)):
                p = [zero] * (t - d)
                yield p + ([one] * (1 + d * 2)) + p

        return _matrix(rows())


class ImageConvolve(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ImageConvolve.html</url>

    <dl>
      <dt>'ImageConvolve[$image$, $kernel$]'
      <dd>Computes the convolution of $image$ using $kernel$.
    </dl>

    >> img = Import["ExampleData/lena.tif"];
    >> ImageConvolve[img, DiamondMatrix[5] / 61]
     = -Image-
    >> ImageConvolve[img, DiskMatrix[5] / 97]
     = -Image-
    >> ImageConvolve[img, BoxMatrix[5] / 121]
     = -Image-
    """

    summary_text = "give the convolution of image with kernel"

    def eval(self, image, kernel, evaluation: Evaluation):
        "%(name)s[image_Image, kernel_?MatrixQ]"
        numpy_kernel = matrix_to_numpy(kernel)
        pixels = pixels_as_float(image.pixels)
        shape = pixels.shape[:2]
        channels = []
        for c in (pixels[:, :, i] for i in range(pixels.shape[2])):
            channels.append(convolve(c.reshape(shape), numpy_kernel, fixed=True))
        return Image(numpy.dstack(channels), image.color_space)


class _MorphologyFilter(_SkimageBuiltin):

    messages = {
        "grayscale": "Your image has been converted to grayscale as color images are not supported yet."
    }

    rules = {"%(name)s[i_Image, r_?RealNumberQ]": "%(name)s[i, BoxMatrix[r]]"}

    def eval(self, image, k, evaluation: Evaluation):
        "%(name)s[image_Image, k_?MatrixQ]"
        if image.color_space != "Grayscale":
            image = image.grayscale()
            evaluation.message(self.get_name(), "grayscale")
        import skimage.morphology

        f = getattr(skimage.morphology, self.get_name(True).lower())
        shape = image.pixels.shape[:2]
        img = f(image.pixels.reshape(shape), matrix_to_numpy(k))
        return Image(img, "Grayscale")


class Dilation(_MorphologyFilter):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Dilation.html</url>

    <dl>
      <dt>'Dilation[$image$, $ker$]'
      <dd>Gives the morphological dilation of $image$ with respect to structuring element $ker$.
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> Dilation[ein, 2.5]
     = -Image-
    """

    summary_text = "give the dilation with respect to a range-r square"


class Erosion(_MorphologyFilter):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Erosion.html</url>

    <dl>
      <dt>'Erosion[$image$, $ker$]'
      <dd>Gives the morphological erosion of $image$ with respect to structuring element $ker$.
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> Erosion[ein, 2.5]
     = -Image-
    """

    summary_text = "give the erotion with respect to a range-r square"


class Opening(_MorphologyFilter):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Opening.html</url>

    <dl>
      <dt>'Opening[$image$, $ker$]'
      <dd>Gives the morphological opening of $image$ with respect to structuring element $ker$.
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> Opening[ein, 2.5]
     = -Image-
    """

    summary_text = "get morphological opening regarding a kernel"


class Closing(_MorphologyFilter):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Closing.html</url>

    <dl>
      <dt>'Closing[$image$, $ker$]'
      <dd>Gives the morphological closing of $image$ with respect to structuring element $ker$.
    </dl>

    >> ein = Import["ExampleData/Einstein.jpg"];
    >> Closing[ein, 2.5]
     = -Image-
    """

    summary_text = "morphological closing regarding a kernel"


class MorphologicalComponents(_SkimageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/MorphologicalComponents.html</url>

    <dl>
      <dt>'MorphologicalComponents[$image$]'
      <dd> Builds a 2-D array in which each pixel of $image$ is replaced \
           by an integer index representing the connected foreground image \
           component in which the pixel lies.

      <dt>'MorphologicalComponents[$image$, $threshold$]'
      <dd> consider any pixel with a value above $threshold$ as the foreground.
    </dl>
    """

    summary_text = "tag connected regions of similar colors"

    rules = {"MorphologicalComponents[i_Image]": "MorphologicalComponents[i, 0]"}

    def eval(self, image, t, evaluation: Evaluation):
        "MorphologicalComponents[image_Image, t_?RealNumberQ]"
        pixels = pixels_as_ubyte(
            pixels_as_float(image.grayscale().pixels) > t.round_to_float()
        )
        import skimage.measure

        return from_python(
            skimage.measure.label(pixels, background=0, connectivity=2).tolist()
        )


# color space


class ImageColorSpace(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ImageColorSpace.html</url>

    <dl>
      <dt>'ImageColorSpace[$image$]'
      <dd>gives $image$'s color space, e.g. "RGB" or "CMYK".
    </dl>

    >> img = Import["ExampleData/lena.tif"];
    >> ImageColorSpace[img]
     = RGB
    """

    summary_text = "colorspace used in the image"

    def eval(self, image, evaluation: Evaluation):
        "ImageColorSpace[image_Image]"
        return String(image.color_space)


class ColorQuantize(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ColorQuantize.html</url>

    <dl>
      <dt>'ColorQuantize[$image$, $n$]'
      <dd>gives a version of $image$ using only $n$ colors.
    </dl>

    >> img = Import["ExampleData/lena.tif"];
    >> ColorQuantize[img, 6]
     = -Image-

    #> ColorQuantize[img, 0]
     : Positive integer expected at position 2 in ColorQuantize[-Image-, 0].
     = ColorQuantize[-Image-, 0]
    #> ColorQuantize[img, -1]
     : Positive integer expected at position 2 in ColorQuantize[-Image-, -1].
     = ColorQuantize[-Image-, -1]
    """

    summary_text = "give an approximation to image that uses only n distinct colors"
    messages = {"intp": "Positive integer expected at position `2` in `1`."}

    def eval(self, image, n: Integer, evaluation: Evaluation):
        "ColorQuantize[image_Image, n_Integer]"
        py_value = n.value
        if py_value <= 0:
            return evaluation.message(
                "ColorQuantize", "intp", Expression(SymbolColorQuantize, image, n), 2
            )
        converted = image.color_convert("RGB")
        if converted is None:
            return
        pixels = pixels_as_ubyte(converted.pixels)
        im = PIL.Image.fromarray(pixels).quantize(py_value)
        im = im.convert("RGB")
        return Image(numpy.array(im), "RGB")


class Threshold(_ImageBuiltin):
    """

    <url>:WMA link:https://reference.wolfram.com/language/ref/Threshold.html</url>

    <dl>
      <dt>'Threshold[$image$]'
      <dd>gives a value suitable for binarizing $image$.
    </dl>

    The option "Method" may be "Cluster" (use Otsu's threshold), "Median", or "Mean".

    >> img = Import["ExampleData/lena.tif"];
    >> Threshold[img]
     = 0.456739
    X> Binarize[img, %]
     = -Image-
    X> Threshold[img, Method -> "Mean"]
     = 0.486458
    X> Threshold[img, Method -> "Median"]
     = 0.504726
    """

    summary_text = "estimate a threshold value for binarize an image"
    if have_skimage_filters:
        options = {"Method": '"Cluster"'}
    else:
        options = {"Method": '"Median"'}

    messages = {
        "illegalmethod": "Method `` is not supported.",
        "skimage": "Please install scikit-image to use Method -> Cluster.",
    }

    def eval(self, image, evaluation: Evaluation, options):
        "Threshold[image_Image, OptionsPattern[Threshold]]"
        pixels = image.grayscale().pixels

        method = self.get_option(options, "Method", evaluation)
        method_name = (
            method.get_string_value()
            if isinstance(method, String)
            else method.to_python()
        )
        if method_name == "Cluster":
            if not have_skimage_filters:
                evaluation.message("ImageResize", "skimage")
                return
            threshold = skimage.filters.threshold_otsu(pixels)
        elif method_name == "Median":
            threshold = numpy.median(pixels)
        elif method_name == "Mean":
            threshold = numpy.mean(pixels)
        else:
            return evaluation.message("Threshold", "illegalmethod", method)

        return MachineReal(float(threshold))


class Binarize(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Binarize.html</url>

    <dl>
      <dt>'Binarize[$image$]'
      <dd>gives a binarized version of $image$, in which each pixel is either 0 or 1.

      <dt>'Binarize[$image$, $t$]'
      <dd>map values $x$ > $t$ to 1, and values $x$ <= $t$ to 0.

      <dt>'Binarize[$image$, {$t1$, $t2$}]'
      <dd>map $t1$ < $x$ < $t2$ to 1, and all other values to 0.
    </dl>

    S> img = Import["ExampleData/lena.tif"];
    S> Binarize[img]
     = -Image-
    S> Binarize[img, 0.7]
     = -Image-
    S> Binarize[img, {0.2, 0.6}]
     = -Image-
    """

    summary_text = "create a binarized image"

    def eval(self, image, evaluation: Evaluation):
        "Binarize[image_Image]"
        image = image.grayscale()
        thresh = (
            Expression(SymbolThreshold, image).evaluate(evaluation).round_to_float()
        )
        if thresh is not None:
            return Image(image.pixels > thresh, "Grayscale")

    def eval_t(self, image, t, evaluation: Evaluation):
        "Binarize[image_Image, t_?RealNumberQ]"
        pixels = image.grayscale().pixels
        return Image(pixels > t.round_to_float(), "Grayscale")

    def eval_t1_t2(self, image, t1, t2, evaluation: Evaluation):
        "Binarize[image_Image, {t1_?RealNumberQ, t2_?RealNumberQ}]"
        pixels = image.grayscale().pixels
        mask1 = pixels > t1.round_to_float()
        mask2 = pixels < t2.round_to_float()
        return Image(mask1 * mask2, "Grayscale")


class ColorSeparate(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ColorSeparate.html</url>

    <dl>
      <dt>'ColorSeparate[$image$]'
      <dd>Gives each channel of $image$ as a separate grayscale image.
    </dl>
    """

    summary_text = "separate color channels"

    def eval(self, image, evaluation: Evaluation):
        "ColorSeparate[image_Image]"
        images = []
        pixels = image.pixels
        if len(pixels.shape) < 3:
            images.append(pixels)
        else:
            for i in range(pixels.shape[2]):
                images.append(Image(pixels[:, :, i], "Grayscale"))
        return ListExpression(*images)


class ColorCombine(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ColorCombine.html</url>

    <dl>
      <dt>'ColorCombine[$channels$, $colorspace$]'
      <dd>Gives an image with $colorspace$ and the respective components described by the given channels.
    </dl>

    >> ColorCombine[{{{1, 0}, {0, 0.75}}, {{0, 1}, {0, 0.25}}, {{0, 0}, {1, 0.5}}}, "RGB"]
     = -Image-
    """

    summary_text = "combine color channels"

    def eval(self, channels, colorspace, evaluation: Evaluation):
        "ColorCombine[channels_List, colorspace_String]"

        py_colorspace = colorspace.get_string_value()
        if py_colorspace not in known_colorspaces:
            return

        numpy_channels = []
        for channel in channels.elements:
            if (
                not Expression(SymbolMatrixQ, channel).evaluate(evaluation)
                is SymbolTrue
            ):
                return
            numpy_channels.append(matrix_to_numpy(channel))

        if not numpy_channels:
            return

        if not all(x.shape == numpy_channels[0].shape for x in numpy_channels[1:]):
            return

        return Image(numpy.dstack(numpy_channels), py_colorspace)


def _linearize(a):
    # this uses a vectorized binary search to compute
    # strictly sequential indices for all values in a.

    orig_shape = a.shape
    a = a.reshape((functools.reduce(lambda x, y: x * y, a.shape),))  # 1 dimension

    u = numpy.unique(a)
    n = len(u)

    lower = numpy.ndarray(a.shape, dtype=int)
    lower.fill(0)
    upper = numpy.ndarray(a.shape, dtype=int)
    upper.fill(n - 1)

    h = numpy.sort(u)
    q = n  # worst case partition size

    while q > 2:
        m = numpy.right_shift(lower + upper, 1)
        f = a <= h[m]
        # (lower, m) vs (m + 1, upper)
        lower = numpy.where(f, lower, m + 1)
        upper = numpy.where(f, m, upper)
        q = (q + 1) // 2

    return numpy.where(a == h[lower], lower, upper).reshape(orig_shape), n


class Colorize(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/Colorize.html</url>

    <dl>
      <dt>'Colorize[$values$]'
      <dd>returns an image where each number in the rectangular matrix \
          $values$ is a pixel and each occurence of the same number is \
          displayed in the same unique color, which is different from the \
          colors of all non-identical numbers.

      <dt>'Colorize[$image$]'
      <dd>gives a colorized version of $image$.
    </dl>

    >> Colorize[{{1.3, 2.1, 1.5}, {1.3, 1.3, 2.1}, {1.3, 2.1, 1.5}}]
     = -Image-

    >> Colorize[{{1, 2}, {2, 2}, {2, 3}}, ColorFunction -> (Blend[{White, Blue}, #]&)]
     = -Image-
    """

    summary_text = "create pseudocolor images"
    options = {"ColorFunction": "Automatic"}

    messages = {
        "cfun": "`1` is neither a gradient ColorData nor a pure function suitable as ColorFunction."
    }

    def eval(self, values, evaluation, options):
        "Colorize[values_, OptionsPattern[%(name)s]]"

        if isinstance(values, Image):
            pixels = values.grayscale().pixels
            matrix = pixels_as_ubyte(pixels.reshape(pixels.shape[:2]))
        else:
            if not Expression(SymbolMatrixQ, values).evaluate(evaluation) is SymbolTrue:
                return
            matrix = matrix_to_numpy(values)

        a, n = _linearize(matrix)
        # the maximum value for n is the number of pixels in a, which is acceptable and never too large.

        color_function = self.get_option(options, "ColorFunction", evaluation)
        if (
            isinstance(color_function, Symbol)
            and color_function.get_name() == "System`Automatic"
        ):
            color_function = String("LakeColors")

        from mathics.builtin.drawing.plot import gradient_palette

        cmap = gradient_palette(color_function, n, evaluation)
        if not cmap:
            evaluation.message("Colorize", "cfun", color_function)
            return

        s = (a.shape[0], a.shape[1], 1)
        p = numpy.transpose(numpy.array([cmap[i] for i in range(n)])[:, 0:3])
        return Image(
            numpy.concatenate([p[i][a].reshape(s) for i in range(3)], axis=2),
            color_space="RGB",
        )


# pixel access


class ImageData(_ImageBuiltin):
    """

    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageData.html</url>

    <dl>
      <dt>'ImageData[$image$]'
      <dd>gives a list of all color values of $image$ as a matrix.

      <dt>'ImageData[$image$, $stype$]'
      <dd>gives a list of color values in type $stype$.
    </dl>

    >> img = Image[{{0.2, 0.4}, {0.9, 0.6}, {0.5, 0.8}}];
    >> ImageData[img]
     = {{0.2, 0.4}, {0.9, 0.6}, {0.5, 0.8}}

    >> ImageData[img, "Byte"]
     = {{51, 102}, {229, 153}, {127, 204}}

    >> ImageData[Image[{{0, 1}, {1, 0}, {1, 1}}], "Bit"]
     = {{0, 1}, {1, 0}, {1, 1}}

    #> ImageData[img, "Bytf"]
     : Unsupported pixel format "Bytf".
     = ImageData[-Image-, Bytf]
    """

    messages = {"pixelfmt": 'Unsupported pixel format "``".'}

    rules = {"ImageData[image_Image]": 'ImageData[image, "Real"]'}
    summary_text = "the array of pixel values from an image"

    def eval(self, image, stype: String, evaluation: Evaluation):
        "ImageData[image_Image, stype_String]"
        pixels = image.pixels
        stype = stype.value
        if stype == "Real":
            pixels = pixels_as_float(pixels)
        elif stype == "Byte":
            pixels = pixels_as_ubyte(pixels)
        elif stype == "Bit16":
            pixels = pixels_as_uint(pixels)
        elif stype == "Bit":
            pixels = pixels.astype(int)
        else:
            return evaluation.message("ImageData", "pixelfmt", stype)
        return from_python(numpy_to_matrix(pixels))


class ImageTake(_ImageBuiltin):
    """
    Crop Image <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageTake.html</url>
    <dl>
      <dt>'ImageTake[$image$, $n$]'
      <dd>gives the first $n$ rows of $image$.

      <dt>'ImageTake[$image$, -$n$]'
      <dd>gives the last $n$ rows of $image$.

      <dt>'ImageTake[$image$, {$r1$, $r2$}]'
      <dd>gives rows $r1$, ..., $r2$ of $image$.

      <dt>'ImageTake[$image$, {$r1$, $r2$}, {$c1$, $c2$}]'
      <dd>gives a cropped version of $image$.
    </dl>

    Crop to the include only the upper half (244 rows) of an image:
    >> alice = Import["ExampleData/MadTeaParty.gif"]; ImageTake[alice, 244]
     = -Image-

    Now crop to the include the lower half of that image:
    >> ImageTake[alice, -244]
     = -Image-

    Just the text around the hat:
    >> ImageTake[alice, {40, 150}, {500, 600}]
     = -Image-

    """

    summary_text = "crop image"

    # FIXME: this probably should be moved out since WMA docs
    # suggest this kind of thing is done across many kinds of
    # images.
    def _image_slice(self, image, i1: Integer, i2: Integer, axis):
        """
        Extracts a slice of an image and return a slice
        indicting a slice, a function flip, that will
        reverse the pixels in an image if necessary.
        """
        n = image.pixels.shape[axis]
        py_i1 = min(max(i1.value - 1, 0), n - 1)
        py_i2 = min(max(i2.value - 1, 0), n - 1)

        def flip(pixels):
            if py_i1 > py_i2:
                return numpy_flip(pixels, axis)
            else:
                return pixels

        return slice(min(py_i1, py_i2), 1 + max(py_i1, py_i2)), flip

    # The reason it is hard to make a rules that turn Image[image, n],
    # or Image[, {r1, r2} into the generic form Image[image, {r1, r2},
    # {c1, c2}] there can be negative numbers, e.g. -n. Also, that
    # missing values, in particular r2 and c2, when filled out can be
    # dependent on the size of the image.

    # FIXME: create common functions to process ranges.
    # FIXME: fix up and use _image_slice.

    def eval_n(self, image, n: Integer, evaluation: Evaluation):
        "ImageTake[image_Image, n_Integer]"
        py_n = n.value
        max_y, max_x = image.pixels.shape[:2]
        if py_n >= 0:
            adjusted_n = min(py_n, max_y)
            pixels = image.pixels[:adjusted_n]
            box_coords = (0, 0, max_x, adjusted_n)
        elif py_n < 0:
            adjusted_n = max(0, max_y + py_n)
            pixels = image.pixels[adjusted_n:]
            box_coords = (0, adjusted_n, max_x, max_y)

        if hasattr(image, "pillow"):
            pillow = image.pillow.crop(box_coords)
            pixels = numpy.asarray(pillow)
            return Image(pixels, image.color_space, pillow=pillow)

        return Image(pixels, image.color_space, pillow=pillow)

    def eval_rows(self, image, r1: Integer, r2: Integer, evaluation: Evaluation):
        "ImageTake[image_Image, {r1_Integer, r2_Integer}]"

        first_row = r1.value
        last_row = r2.value

        max_row, max_col = image.pixels.shape[:2]
        adjusted_first_row = (
            min(first_row, max_row) if first_row > 0 else max(0, max_row + first_row)
        )
        adjusted_last_row = (
            min(last_row, max_row) if last_row > 0 else max(0, max_row + first_row)
        )

        # More complicated in that it reverses the data?
        # if adjusted_first_row > adjusted_last_row:
        #     adjusted_first_row, adjusted_last_row = adjusted_last_row, adjusted_first_row

        pixels = image.pixels[adjusted_first_row:adjusted_last_row]

        if hasattr(image, "pillow"):
            box_coords = (0, adjusted_first_row, max_col, adjusted_last_row)
            pillow = image.pillow.crop(box_coords)
            pixels = numpy.asarray(pillow)
            return Image(pixels, image.color_space, pillow=pillow)

        pixels = image.pixels[adjusted_first_row:adjusted_last_row]
        return Image(pixels, image.color_space, pillow=pillow)

    def eval_rows_cols(
        self, image, r1: Integer, r2: Integer, c1: Integer, c2: Integer, evaluation
    ):
        "ImageTake[image_Image, {r1_Integer, r2_Integer}, {c1_Integer, c2_Integer}]"

        first_row = r1.value
        last_row = r2.value
        first_col = c1.value
        last_col = c2.value

        max_row, max_col = image.pixels.shape[:2]
        adjusted_first_row = (
            min(first_row, max_row) if first_row > 0 else max(0, max_row + first_row)
        )
        adjusted_last_row = (
            min(last_row, max_row) if last_row > 0 else max(0, max_row + last_row)
        )
        adjusted_first_col = (
            min(first_col, max_col) if first_col > 0 else max(0, max_col + first_col)
        )
        adjusted_last_col = (
            min(last_col, max_col) if last_col > 0 else max(0, max_col + last_col)
        )

        # if adjusted_first_row > adjusted_last_row:
        #     adjusted_first_row, adjusted_last_row = adjusted_last_row, adjusted_first_row

        # if adjusted_first_col > adjusted_last_col:
        #     adjusted_first_col, adjusted_last_col = adjusted_last_col, adjusted_first_col

        pixels = image.pixels[
            adjusted_first_col:adjusted_last_col, adjusted_last_row:adjusted_last_row
        ]

        if hasattr(image, "pillow"):
            box_coords = (
                adjusted_first_col,
                adjusted_first_row,
                adjusted_last_col,
                adjusted_last_row,
            )
            pillow = image.pillow.crop(box_coords)
            pixels = numpy.asarray(pillow)
            return Image(pixels, image.color_space, pillow=pillow)

        pixels = image.pixels[adjusted_first_row:adjusted_last_row]
        return Image(pixels, image.color_space, pillow=pillow)

    # Older code we can remove after we condence existing code that looks like this
    #
    # def eval_rows(self, image, r1: Integer, r2: Integer, evaluation: Evaluation):
    #     "ImageTake[image_Image, {r1_Integer, r2_Integer}]"
    #     s, f = self._slice(image, r1, r2, 0)
    #     return Image(f(image.pixels[s]), image.color_space)

    # def eval_rows_cols(
    #     self, image, r1: Integer, r2: Integer, c1: Integer, c2: Integer, evaluation
    # ):
    #     "ImageTake[image_Image, {r1_Integer, r2_Integer}, {c1_Integer, c2_Integer}]"
    #     sr, fr = self._slice(image, r1, r2, 0)
    #     sc, fc = self._slice(image, c1, c2, 1)
    #     return Image(fc(fr(image.pixels[sr, sc])), image.color_space)


class PixelValue(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/PixelValue.html</url>

    <dl>
      <dt>'PixelValue[$image$, {$x$, $y$}]'
      <dd>gives the value of the pixel at position {$x$, $y$} in $image$.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> PixelValue[lena, {1, 1}]
     = {0.321569, 0.0862745, 0.223529}
    #> {82 / 255, 22 / 255, 57 / 255} // N  (* pixel byte values from bottom left corner *)
     = {0.321569, 0.0862745, 0.223529}

    #> PixelValue[lena, {0, 1}];
     : Padding not implemented for PixelValue.
    #> PixelValue[lena, {512, 1}]
     = {0.72549, 0.290196, 0.317647}
    #> PixelValue[lena, {513, 1}];
     : Padding not implemented for PixelValue.
    #> PixelValue[lena, {1, 0}];
     : Padding not implemented for PixelValue.
    #> PixelValue[lena, {1, 512}]
     = {0.886275, 0.537255, 0.490196}
    #> PixelValue[lena, {1, 513}];
     : Padding not implemented for PixelValue.
    """

    messages = {"nopad": "Padding not implemented for PixelValue."}

    summary_text = "get pixel value of image at a given position"

    def eval(self, image, x, y, evaluation: Evaluation):
        "PixelValue[image_Image, {x_?RealNumberQ, y_?RealNumberQ}]"
        x = int(x.round_to_float())
        y = int(y.round_to_float())
        height = image.pixels.shape[0]
        width = image.pixels.shape[1]
        if not (1 <= x <= width and 1 <= y <= height):
            return evaluation.message("PixelValue", "nopad")
        pixel = pixels_as_float(image.pixels)[height - y, x - 1]
        if isinstance(pixel, (numpy.ndarray, numpy.generic, list)):
            return ListExpression(*[MachineReal(float(x)) for x in list(pixel)])
        else:
            return MachineReal(float(pixel))


class PixelValuePositions(_ImageBuiltin):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/PixelValuePositions.html</url>

    <dl>
      <dt>'PixelValuePositions[$image$, $val$]'
      <dd>gives the positions of all pixels in $image$ that have value $val$.
    </dl>

    >> PixelValuePositions[Image[{{0, 1}, {1, 0}, {1, 1}}], 1]
     = {{1, 1}, {1, 2}, {2, 1}, {2, 3}}

    >> PixelValuePositions[Image[{{0.2, 0.4}, {0.9, 0.6}, {0.3, 0.8}}], 0.5, 0.15]
     = {{2, 2}, {2, 3}}

    >> img = Import["ExampleData/lena.tif"];
    >> PixelValuePositions[img, 3 / 255, 0.5 / 255]
     = {{180, 192, 2}, {181, 192, 2}, {181, 193, 2}, {188, 204, 2}, {265, 314, 2}, {364, 77, 2}, {365, 72, 2}, {365, 73, 2}, {365, 77, 2}, {366, 70, 2}, {367, 65, 2}}
    >> PixelValue[img, {180, 192}]
     = {0.25098, 0.0117647, 0.215686}
    """

    rules = {
        "PixelValuePositions[image_Image, val_?RealNumberQ]": "PixelValuePositions[image, val, 0]"
    }

    summary_text = "list the position of pixels with a given value"

    def eval(self, image, val, d, evaluation: Evaluation):
        "PixelValuePositions[image_Image, val_?RealNumberQ, d_?RealNumberQ]"
        val = val.round_to_float()
        d = d.round_to_float()

        positions = numpy.argwhere(
            numpy.isclose(pixels_as_float(image.pixels), val, atol=d, rtol=0)
        )

        # python indexes from 0 at top left -> indices from 1 starting at bottom left
        # if single channel then ommit channel indices
        height = image.pixels.shape[0]
        if image.pixels.shape[2] == 1:
            result = sorted((j + 1, height - i) for i, j, k in positions.tolist())
        else:
            result = sorted(
                (j + 1, height - i, k + 1) for i, j, k in positions.tolist()
            )
        return ListExpression(
            *(to_mathics_list(*arg, elements_conversion_fn=Integer) for arg in result)
        )


# image attribute queries


class ImageDimensions(_ImageBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ImageDimensions.html</url>

    <dl>
      <dt>'ImageDimensions[$image$]'
      <dd>Returns the dimensions {$width$, $height$} of $image$ in pixels.
    </dl>

    >> lena = Import["ExampleData/lena.tif"];
    >> ImageDimensions[lena]
     = {512, 512}

    >> ImageDimensions[RandomImage[1, {50, 70}]]
     = {50, 70}
    """

    summary_text = "get the pixel dimensions of an image"

    def eval(self, image, evaluation: Evaluation):
        "ImageDimensions[image_Image]"
        return to_mathics_list(*image.dimensions(), elements_conversion_fn=Integer)


class ImageAspectRatio(_ImageBuiltin):
    """
    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageAspectRatio.html</url>

    <dl>
      <dt>'ImageAspectRatio[$image$]'
      <dd>gives the aspect ratio of $image$.
    </dl>

    >> img = Import["ExampleData/lena.tif"];
    >> ImageAspectRatio[img]
     = 1

    >> ImageAspectRatio[Image[{{0, 1}, {1, 0}, {1, 1}}]]
     = 3 / 2
    """

    summary_text = "give the ratio of height to width of an image"

    def eval(self, image, evaluation: Evaluation):
        "ImageAspectRatio[image_Image]"
        dim = image.dimensions()
        return Expression(SymbolDivide, Integer(dim[1]), Integer(dim[0]))


class ImageChannels(_ImageBuiltin):
    """
    <url>:WMA link:
    https://reference.wolfram.com/language/ref/ImageChannels.html</url>

    <dl>
    <dt>'ImageChannels[$image$]'
      <dd>gives the number of channels in $image$.
    </dl>

    >> ImageChannels[Image[{{0, 1}, {1, 0}}]]
     = 1

    >> img = Import["ExampleData/lena.tif"];
    >> ImageChannels[img]
     = 3
    """

    summary_text = "get number of channels present in the data for an image"

    def eval(self, image, evaluation: Evaluation):
        "ImageChannels[image_Image]"
        return Integer(image.channels())


class ImageType(_ImageBuiltin):
    """
    <url>
    :WMA link:https://reference.wolfram.com/language/ref/ImageType.html</url>

    <dl>
      <dt>'ImageType[$image$]'
      <dd>gives the interval storage type of $image$, e.g. "Real", "Bit32", or "Bit".
    </dl>

    >> img = Import["ExampleData/lena.tif"];
    >> ImageType[img]
     = Byte

    >> ImageType[Image[{{0, 1}, {1, 0}}]]
     = Real

    X> ImageType[Binarize[img]]
     = Bit

    """

    summary_text = "type of values used for each pixel element in an image"

    def eval(self, image, evaluation: Evaluation):
        "ImageType[image_Image]"
        return String(image.storage_type())


class BinaryImageQ(_ImageTest):
    """
    <url>:WMA link:
    https://reference.wolfram.com/language/ref/BinaryImageQ.html</url>

    <dl>
      <dt>'BinaryImageQ[$image]'
      <dd>returns True if the pixels of $image are binary bit values, and False otherwise.
    </dl>

    S> img = Import["ExampleData/lena.tif"];
    S> BinaryImageQ[img]
     = False

    S> BinaryImageQ[Binarize[img]]
     = ...
     : ...
    """

    summary_text = "test whether pixels in an image are binary bit values"

    def test(self, expr):
        return isinstance(expr, Image) and expr.storage_type() == "Bit"


# Image core classes


def _image_pixels(matrix):
    try:
        pixels = numpy.array(matrix, dtype="float64")
    except ValueError:  # irregular array, e.g. {{0, 1}, {0, 1, 1}}
        return None
    shape = pixels.shape
    if len(shape) == 2 or (len(shape) == 3 and shape[2] in (1, 3, 4)):
        return pixels
    else:
        return None


class ImageQ(_ImageTest):
    """
    <url>:WMA link:https://reference.wolfram.com/language/ref/ImageQ.html</url>

    <dl>
      <dt>'ImageQ[Image[$pixels]]'
      <dd>returns True if $pixels has dimensions from which an Image can be constructed, and False otherwise.
    </dl>

    >> ImageQ[Image[{{0, 1}, {1, 0}}]]
     = True

    >> ImageQ[Image[{{{0, 0, 0}, {0, 1, 0}}, {{0, 1, 0}, {0, 1, 1}}}]]
     = True

    >> ImageQ[Image[{{{0, 0, 0}, {0, 1}}, {{0, 1, 0}, {0, 1, 1}}}]]
     = False

    >> ImageQ[Image[{1, 0, 1}]]
     = False

    >> ImageQ["abc"]
     = False
    """

    summary_text = "test whether is a valid image"

    def test(self, expr):
        return isinstance(expr, Image)


class Image(Atom):
    class_head_name = "System`Image"

    # FIXME: pixels should be optional if pillow is provided.
    def __init__(self, pixels, color_space, pillow=None, metadata={}, **kwargs):
        super(Image, self).__init__(**kwargs)

        if pillow is not None:
            self.pillow = pillow

        self.pixels = pixels

        if len(pixels.shape) == 2:
            pixels = pixels.reshape(list(pixels.shape) + [1])

        # FIXME: assigning pixels should be done lazily on demand.
        # Turn pixels into a property? Include a setter?

        self.pixels = pixels

        self.color_space = color_space
        self.metadata = metadata

        # Set a value for self.__hash__() once so that every time
        # it is used this is fast. Note that in contrast to the
        # cached object key, the hash key needs to be unique across all
        # Python objects, so we include the class in the
        # event that different objects have the same Python value
        self.hash = hash(
            (
                SymbolImage,
                self.pixels.tobytes(),
                self.color_space,
                frozenset(self.metadata.items()),
            )
        )

    def atom_to_boxes(self, form, evaluation: Evaluation) -> ImageBox:
        """
        Converts our internal Image object into a PNG base64-encoded.
        """
        pixels = pixels_as_ubyte(self.color_convert("RGB", True).pixels)
        shape = pixels.shape

        width = shape[1]
        height = shape[0]
        scaled_width = width
        scaled_height = height

        # If the image was created from PIL, use that rather than
        # reconstruct it from pixels which we can get wrong.
        # In particular getting color-mapping info right can be
        # tricky.
        if hasattr(self, "pillow"):
            pillow = deepcopy(self.pillow)
        else:
            pixels_format = "RGBA" if len(shape) >= 3 and shape[2] == 4 else "RGB"
            pillow = PIL.Image.fromarray(pixels, pixels_format)

        # if the image is very small, scale it up using nearest neighbour.
        min_size = 128
        if width < min_size and height < min_size:
            scale = min_size / max(width, height)
            scaled_width = int(scale * width)
            scaled_height = int(scale * height)
            pillow = pillow.resize(
                (scaled_height, scaled_width), resample=PIL.Image.NEAREST
            )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            stream = BytesIO()
            pillow.save(stream, format="png")
            stream.seek(0)
            contents = stream.read()
            stream.close()

        encoded = base64.b64encode(contents)
        encoded = b"data:image/png;base64," + encoded

        return ImageBox(
            String(encoded.decode("utf-8")),
            Integer(scaled_width),
            Integer(scaled_height),
        )

    # __hash__ is defined so that we can store Number-derived objects
    # in a set or dictionary.
    def __hash__(self):
        return self.hash

    def __str__(self):
        return "-Image-"

    def color_convert(self, to_color_space, preserve_alpha=True):
        if to_color_space == self.color_space and preserve_alpha:
            return self
        else:
            pixels = pixels_as_float(self.pixels)
            converted = convert_color(
                pixels, self.color_space, to_color_space, preserve_alpha
            )
            if converted is None:
                return None
            return Image(converted, to_color_space)

    def channels(self):
        return self.pixels.shape[2]

    def default_format(self, evaluation, form):
        return "-Image-"

    def dimensions(self) -> Tuple[int, int]:
        shape = self.pixels.shape
        return shape[1], shape[0]

    def do_copy(self):
        return Image(self.pixels, self.color_space, self.metadata)

    def filter(self, f):  # apply PIL filters component-wise
        pixels = self.pixels
        n = pixels.shape[2]
        channels = [
            f(PIL.Image.fromarray(c, "L")) for c in (pixels[:, :, i] for i in range(n))
        ]
        return Image(numpy.dstack(channels), self.color_space)

    def get_sort_key(self, pattern_sort=False) -> tuple:
        if pattern_sort:
            # If pattern_sort=True, returns the sort key that matches to an Atom.
            return super(Image, self).get_sort_key(True)
        else:
            # If pattern is False, return a sort_key for the expression `Image[]`,
            # but with a `2` instead of `1` in the 5th position,
            # and adding two extra fields: the length in the 5th position,
            # and a hash in the 6th place.
            return (1, 3, SymbolImage, len(self.pixels), tuple(), 2, hash(self))

    def grayscale(self):
        return self.color_convert("Grayscale")

    def pil(self):

        if hasattr(self, "pillow") and self.pillow is not None:
            return self.pillow

        # see https://pillow.readthedocs.io/en/stable/handbook/concepts.html

        n = self.channels()

        if n == 1:
            dtype = self.pixels.dtype

            if dtype in (numpy.float32, numpy.float64):
                pixels = self.pixels.astype(numpy.float32)
                mode = "F"
            elif dtype == numpy.uint32:
                pixels = self.pixels
                mode = "I"
            else:
                pixels = pixels_as_ubyte(self.pixels)
                mode = "L"

            pixels = pixels.reshape(pixels.shape[:2])
        elif n == 3:
            if self.color_space == "LAB":
                mode = "LAB"
                pixels = self.pixels
            elif self.color_space == "HSB":
                mode = "HSV"
                pixels = self.pixels
            elif self.color_space == "RGB":
                mode = "RGB"
                pixels = self.pixels
            else:
                mode = "RGB"
                pixels = self.color_convert("RGB").pixels

            pixels = pixels_as_ubyte(pixels)
        elif n == 4:
            if self.color_space == "CMYK":
                mode = "CMYK"
                pixels = self.pixels
            elif self.color_space == "RGB":
                mode = "RGBA"
                pixels = self.pixels
            else:
                mode = "RGBA"
                pixels = self.color_convert("RGB").pixels

            pixels = pixels_as_ubyte(pixels)
        else:
            raise NotImplementedError

        return PIL.Image.fromarray(pixels, mode)

    def options(self):
        return ListExpression(
            Expression(SymbolRule, String("ColorSpace"), String(self.color_space)),
            Expression(SymbolRule, String("MetaInformation"), self.metadata),
        )

    def sameQ(self, other) -> bool:
        """Mathics SameQ"""
        if not isinstance(other, Image):
            return False
        if self.color_space != other.color_space or self.metadata != other.metadata:
            return False
        return numpy.array_equal(self.pixels, other.pixels)

    def storage_type(self):
        dtype = self.pixels.dtype
        if dtype in (numpy.float32, numpy.float64):
            return "Real"
        elif dtype == numpy.uint32:
            return "Bit32"
        elif dtype == numpy.uint16:
            return "Bit16"
        elif dtype == numpy.uint8:
            return "Byte"
        elif dtype == bool:
            return "Bit"
        else:
            return str(dtype)

    def to_python(self, *args, **kwargs):
        return self.pixels


class ImageAtom(AtomBuiltin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/ImageAtom.html</url>

    <dl>
      <dt>'Image[...]'
      <dd> produces the internal representation of an image from an array \
          of values for the pixels.
    </dl>

    #> Image[{{{1,1,0},{0,1,1}}, {{1,0,1},{1,1,0}}}]
     = -Image-

    #> Image[{{{0,0,0,0.25},{0,0,0,0.5}}, {{0,0,0,0.5},{0,0,0,0.75}}}]
     = -Image-
    """

    summary_text = "get internal representation of an image"
    requires = _image_requires

    def eval_create(self, array, evaluation: Evaluation):
        "Image[array_]"
        pixels = _image_pixels(array.to_python())
        if pixels is not None:
            shape = pixels.shape
            is_rgb = len(shape) == 3 and shape[2] in (3, 4)
            return Image(pixels.clip(0, 1), "RGB" if is_rgb else "Grayscale")
        else:
            return Expression(SymbolImage, array)


# complex operations


class TextRecognize(Builtin):
    """

    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/TextRecognize.html</url>

    <dl>
      <dt>'TextRecognize[{$image$}]'
      <dd>Recognizes text in $image$ and returns it as string.
    </dl>
    """

    messages = {
        "tool": "No text recognition tools were found in the paths available to the Mathics kernel.",
        "langinv": "No language data for `1` is available.",
        "lang": "Language `1` is not supported in your installation of `2`. Please install it.",
    }

    options = {"Language": '"English"'}

    requires = _image_requires + ("pyocr",)

    summary_text = "recognize text in an image"

    def eval(self, image, evaluation, options):
        "TextRecognize[image_Image, OptionsPattern[%(name)s]]"
        import pyocr

        from mathics.builtin.codetables import iso639_3

        language = self.get_option(options, "Language", evaluation)
        if not isinstance(language, String):
            return
        py_language = language.get_string_value()
        py_language_code = iso639_3.get(py_language)

        if py_language_code is None:
            evaluation.message("TextRecognize", "langcode", py_language)
            return

        tools = pyocr.get_available_tools()
        if not tools:
            evaluation.message("TextRecognize", "tool")
            return
        best_tool = tools[0]

        langs = best_tool.get_available_languages()
        if py_language_code not in langs:
            # if we use Tesseract, then this means copying the necessary language files from
            # https://github.com/tesseract-ocr/tessdatainstalling to tessdata, which is
            # usually located at /usr/share/tessdata or similar, but there's no API to query
            # the exact location, so we cannot, for now, give a better message.

            evaluation.message(
                "TextRecognize", "lang", py_language, best_tool.get_name()
            )
            return

        import pyocr.builders

        text = best_tool.image_to_string(
            image.pil(), lang=py_language_code, builder=pyocr.builders.TextBuilder()
        )

        if isinstance(text, (list, tuple)):
            text = "\n".join(text)

        return String(text)


class WordCloud(Builtin):
    """
    <url>
    :WMA link:
    https://reference.wolfram.com/language/ref/WordCloud.html</url>

    <dl>
      <dt>'WordCloud[{$word1$, $word2$, ...}]'
      <dd>Gives a word cloud with the given list of words.

      <dt>'WordCloud[{$weight1$ -> $word1$, $weight2$ -> $word2$, ...}]'
      <dd>Gives a word cloud with the words weighted using the given weights.

      <dt>'WordCloud[{$weight1$, $weight2$, ...} -> {$word1$, $word2$, ...}]'
      <dd>Also gives a word cloud with the words weighted using the given weights.

      <dt>'WordCloud[{{$word1$, $weight1$}, {$word2$, $weight2$}, ...}]'
      <dd>Gives a word cloud with the words weighted using the given weights.
    </dl>

    >> WordCloud[StringSplit[Import["ExampleData/EinsteinSzilLetter.txt", CharacterEncoding->"UTF8"]]]
     = -Image-

    >> WordCloud[Range[50] -> ToString /@ Range[50]]
     = -Image-
    """

    # this is the palettable.colorbrewer.qualitative.Dark2_8 palette
    default_colors = (
        (27, 158, 119),
        (217, 95, 2),
        (117, 112, 179),
        (231, 41, 138),
        (102, 166, 30),
        (230, 171, 2),
        (166, 118, 29),
        (102, 102, 102),
    )

    options = {
        "IgnoreCase": "True",
        "ImageSize": "Automatic",
        "MaxItems": "Automatic",
    }

    requires = _image_requires + ("wordcloud",)

    summary_text = "show a word cloud from a list of words"

    def eval_words_weights(self, weights, words, evaluation, options):
        "WordCloud[weights_List -> words_List, OptionsPattern[%(name)s]]"
        if len(weights.elements) != len(words.elements):
            return

        def weights_and_words():
            for weight, word in zip(weights.elements, words.elements):
                yield weight.round_to_float(), word.get_string_value()

        return self._word_cloud(weights_and_words(), evaluation, options)

    def eval_words(self, words, evaluation, options):
        "WordCloud[words_List, OptionsPattern[%(name)s]]"

        if not words:
            return
        elif isinstance(words.elements[0], String):

            def weights_and_words():
                for word in words.elements:
                    yield 1, word.get_string_value()

        else:

            def weights_and_words():
                for word in words.elements:
                    if len(word.elements) != 2:
                        raise ValueError

                    head_name = word.get_head_name()
                    if head_name == "System`Rule":
                        weight, s = word.elements
                    elif head_name == "System`List":
                        s, weight = word.elements
                    else:
                        raise ValueError

                    yield weight.round_to_float(), s.get_string_value()

        try:
            return self._word_cloud(weights_and_words(), evaluation, options)
        except ValueError:
            return

    def _word_cloud(self, words, evaluation, options):
        ignore_case = self.get_option(options, "IgnoreCase", evaluation) is Symbol(
            "True"
        )

        freq = defaultdict(int)
        for py_weight, py_word in words:
            if py_word is None or py_weight is None:
                return
            key = py_word.lower() if ignore_case else py_word
            freq[key] += py_weight

        max_items = self.get_option(options, "MaxItems", evaluation)
        if isinstance(max_items, Integer):
            py_max_items = max_items.get_int_value()
        else:
            py_max_items = 200

        image_size = self.get_option(options, "ImageSize", evaluation)
        if image_size is Symbol("Automatic"):
            py_image_size = (800, 600)
        elif (
            image_size.get_head_name() == "System`List"
            and len(image_size.elements) == 2
        ):
            py_image_size = []
            for element in image_size.elements:
                if not isinstance(element, Integer):
                    return
                py_image_size.append(element.get_int_value())
        elif isinstance(image_size, Integer):
            size = image_size.get_int_value()
            py_image_size = (size, size)
        else:
            return

        # inspired by http://minimaxir.com/2016/05/wordclouds/
        import random

        def color_func(
            word, font_size, position, orientation, random_state=None, **kwargs
        ):
            return self.default_colors[random.randint(0, 7)]

        font_base_path = osp.join(osp.dirname(osp.abspath(__file__)), "..", "fonts")

        font_path = osp.realpath(font_base_path + "AmaticSC-Bold.ttf")
        if not osp.exists(font_path):
            font_path = None

        from wordcloud import WordCloud

        wc = WordCloud(
            width=py_image_size[0],
            height=py_image_size[1],
            font_path=font_path,
            max_font_size=300,
            mode="RGB",
            background_color="white",
            max_words=py_max_items,
            color_func=color_func,
            random_state=42,
            stopwords=set(),
        )
        wc.generate_from_frequencies(freq)

        image = wc.to_image()
        return Image(numpy.array(image), "RGB")
