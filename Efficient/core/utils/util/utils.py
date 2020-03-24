import os
import random

import cv2
import mxnet as mx
import numpy as np
import onnx
from matplotlib import pyplot as plt
from mxnet.base import MXNetError
from mxnet.gluon import HybridBlock
from mxnet.gluon.nn import HybridSequential, Conv2D
from onnx import checker

from core.model.backbone.Bifpn import get_bifpn


def check_onnx(onnx_path):
    '''
        Now we can check validity of the converted ONNX model by using ONNX checker tool.
        The tool will validate the model by checking if the content contains valid protobuf:
        If the converted protobuf format doesn’t qualify to ONNX proto specifications,
        the checker will throw errors, but in this case it successfully passes.
        This method confirms exported model protobuf is valid.
        Now, the model is ready to be imported in other frameworks for inference!
    '''

    model_proto = onnx.load(onnx_path)

    # Check if converted ONNX protobuf is valid
    checker.check_graph(model_proto.graph)


# test시 nms 통과후 적용
def plot_bbox(img, bboxes, scores=None, labels=None, thresh=0.5,
              class_names=None, colors=None, reverse_rgb=False, absolute_coordinates=True,
              image_show=False, image_save=False, image_save_path=None, image_name=None):
    """Visualize bounding boxes.
    Parameters
    ----------
    img : numpy.ndarray or mxnet.nd.NDArray
        Image with shape `H, W, 3`.(range 0 ~ 255 - uint8)
    bboxes : numpy.ndarray or mxnet.nd.NDArray
        Bounding boxes with shape `N, 4`. Where `N` is the number of boxes.
    scores : numpy.ndarray or mxnet.nd.NDArray, optional
        Confidence scores of the provided `bboxes` with shape `N`.
    labels : numpy.ndarray or mxnet.nd.NDArray, optional
        Class labels of the provided `bboxes` with shape `N`.
    thresh : float, optional, default 0.5
        Display threshold if `scores` is provided. Scores with less than `thresh`
        will be ignored in display, this is visually more elegant if you have
        a large number of bounding boxes with very small scores.
    class_names : list of str, optional
        Description of parameter `class_names`.
    colors : dict, optional
        You can provide desired colors as {0: (255, 0, 0), 1:(0, 255, 0), ...}, otherwise
        random colors will be substituted.
    reverse_rgb : bool, optional
        Reverse RGB<->BGR orders if `True`.
    absolute_coordinates : bool
        If `True`, absolute coordinates will be considered, otherwise coordinates
        are interpreted as in range(0, 1).
    """
    if labels is not None and not len(bboxes) == len(labels):
        raise ValueError('The length of labels and bboxes mismatch, {} vs {}'
                         .format(len(labels), len(bboxes)))
    if scores is not None and not len(bboxes) == len(scores):
        raise ValueError('The length of scores and bboxes mismatch, {} vs {}'
                         .format(len(scores), len(bboxes)))

    if image_save:
        if not os.path.exists(image_save_path):
            os.makedirs(image_save_path)

    img = img.astype(np.uint8)

    if len(bboxes) < 1:
        img = img.asnumpy()
        if image_save:
            cv2.imwrite(os.path.join(image_save_path, image_name + ".jpg"), img)
        if image_show:
            cv2.imshow(image_name, img)
            cv2.waitKey(0)
    else:
        if isinstance(img, mx.nd.NDArray):
            img = img.asnumpy()
        if isinstance(bboxes, mx.nd.NDArray):
            bboxes = bboxes.asnumpy()
        if isinstance(labels, mx.nd.NDArray):
            labels = labels.asnumpy()
        if isinstance(scores, mx.nd.NDArray):
            scores = scores.asnumpy()

        if reverse_rgb:
            img[:, :, (0, 1, 2)] = img[:, :, (2, 1, 0)]

        copied_img = img.copy()

        if not absolute_coordinates:
            # convert to absolute coordinates using image shape
            height = img.shape[0]
            width = img.shape[1]
            bboxes[:, (0, 2)] *= width
            bboxes[:, (1, 3)] *= height

        # use random colors if None is provided
        if colors is None:
            colors = dict()

        for i, bbox in enumerate(bboxes):
            if scores is not None and scores.ravel()[i] < thresh:  # threshold보다 작은 것 무시
                continue
            if labels is not None and labels.ravel()[i] < 0:  # 0이하 인것들 인것 무시
                continue

            cls_id = int(labels.ravel()[i]) if labels is not None else -1
            if cls_id not in colors:
                if class_names is not None and cls_id != -1:
                    colors[cls_id] = plt.get_cmap('hsv')(cls_id / len(class_names))
                else:
                    colors[cls_id] = (random.random(), random.random(), random.random())
            denorm_color = [x * 255 for x in colors[cls_id]]

            bbox[np.isinf(bbox)] = 0
            bbox[bbox < 0] = 0
            xmin, ymin, xmax, ymax = [int(np.rint(x)) for x in bbox]
            try:
                '''
                colors[cls_id] -> 기본적으로 list, tuple 자료형에 동작함

                numpy인 경우 float64만 동작함 - 나머지 동작안함
                다른 자료형 같은 경우는 tolist로 바꾼 다음 넣어줘야 동작함.
                '''
                cv2.rectangle(img, (xmin, ymin), (xmax, ymax), denorm_color, thickness=3)
            except Exception as E:
                print(E)

            if class_names is not None and cls_id < len(class_names):
                class_name = class_names[cls_id]
            else:
                class_name = str(cls_id) if cls_id >= 0 else ''

            score = '{:.2f}'.format(scores.ravel()[i]) if scores is not None else ''

            if class_name or score:
                cv2.putText(copied_img,
                            text='{} {}'.format(class_name, score), \
                            org=(xmin + 7, ymin + 20), \
                            fontFace=cv2.FONT_HERSHEY_TRIPLEX, \
                            fontScale=0.5, \
                            color=[255, 255, 255], \
                            thickness=1, bottomLeftOrigin=False)

        result = cv2.addWeighted(img, 0.5, copied_img, 0.5, 0)

        if image_save:
            cv2.imwrite(os.path.join(image_save_path, image_name + ".jpg"), result)
        if image_show:
            cv2.imshow(image_name, result)
            cv2.waitKey(0)

        return result


"""Helper utils for export HybridBlock to symbols."""
# from gluoncv.utils import export_block 에서 아주 조금 수정

'''
c++에서의 일을 덜 수 있다.
Use preprocess=True will add a default preprocess layer above the network, 
which will subtract mean [123.675, 116.28, 103.53], divide std [58.395, 57.12, 57.375],
and convert original image (B, H, W, C and range [0, 255]) to tensor (B, C, H, W) as network input.
This is the default preprocess behavior of all GluonCV pre-trained models. With this preprocess head, 
you can use raw RGB image in C++ without explicitly applying these operations.
'''


class _DefaultPreprocess(HybridBlock):
    """Default preprocess block used by GluonCV.

    The default preprocess block includes:

        - mean [123.675, 116.28, 103.53]

        - std [58.395, 57.12, 57.375]

        - transpose to (B, 3, H, W)

    It is used to transform from resized original images with shape (1, H, W, 3) or (B, H, W, 3)
    in range (0, 255) and RGB color format.

    """

    def __init__(self, **kwargs):
        super(_DefaultPreprocess, self).__init__(**kwargs)
        with self.name_scope():
            mean = mx.nd.array([123.675, 116.28, 103.53]).reshape((1, 1, 1, 3))
            scale = mx.nd.array([58.395, 57.12, 57.375]).reshape((1, 1, 1, 3))
            self.init_mean = self.params.get_constant('init_mean', mean)
            self.init_scale = self.params.get_constant('init_scale', scale)

    # pylint: disable=arguments-differ
    def hybrid_forward(self, F, x, init_mean, init_scale):
        x = F.broadcast_minus(x, init_mean)
        x = F.broadcast_div(x, init_scale)
        x = F.transpose(x, axes=(0, 3, 1, 2))
        return x


def export_block_for_cplusplus(path=None, block=None, data_shape=None, epoch=0, preprocess=True,
                               layout='HWC',
                               ctx=mx.cpu(), remove_amp_cast=True):
    """Helper function to export a HybridBlock to symbol JSON to be used by
    `SymbolBlock.imports`, `mxnet.mod.Module` or the C++ interface..

    Parameters
    ----------
    path : str
        Path to save model.
        Two files path-symbol.json and path-xxxx.params will be created,
        where xxxx is the 4 digits epoch number.
    block : mxnet.gluon.HybridBlock
        The hybridizable block. Note that normal gluon.Block is not supported.
    data_shape : tuple of int, default is None
        Fake data shape just for export purpose, in format (H, W, C).
        If you don't specify ``data_shape``, `export_block` will try use some common data_shapes,
        e.g., (224, 224, 3), (256, 256, 3), (299, 299, 3), (512, 512, 3)...
        If any of this ``data_shape`` goes through, the export will succeed.
    epoch : int
        Epoch number of saved model.
    preprocess : mxnet.gluon.HybridBlock, default is True.
        Preprocess block prior to the network.
        By default (True), it will subtract mean [123.675, 116.28, 103.53], divide
        std [58.395, 57.12, 57.375], and convert original image (B, H, W, C and range [0, 255]) to
        tensor (B, C, H, W) as network input. This is the default preprocess behavior of all GluonCV
        pre-trained models.
        You can use custom pre-process hybrid block or disable by set ``preprocess=None``.
    layout : str, default is 'HWC'
        The layout for raw input data. By default is HWC. Supports 'HWC' and 'CHW'.
        Note that image channel order is always RGB.
    ctx: mx.Context, default mx.cpu()
        Network context.

    Returns
    -------
    preprocessed block

    """
    # input image layout
    if data_shape is None:
        data_shapes = [(s, s, 3) for s in (224, 256, 299, 300, 320, 416, 512, 600)]
    else:
        data_shapes = [data_shape]

    '''
    c++ 에서 inference 할 때,
    데이터를 0 ~ 1 범위로 바꾸고, mxnet 입력형태인 (1, C, H, W)로 바꿀 필요가 없다.

    그대로 
    '''
    if preprocess:
        # add preprocess block
        if preprocess is True:
            preprocess = _DefaultPreprocess()
        else:
            if not isinstance(preprocess, HybridBlock):
                raise TypeError("preprocess must be HybridBlock, given {}".format(type(preprocess)))
        wrapper_block = HybridSequential()
        preprocess.initialize(ctx=ctx)
        wrapper_block.add(preprocess)
        wrapper_block.add(block)
    else:
        wrapper_block = block
    wrapper_block.collect_params().reset_ctx(ctx)

    # try different data_shape if possible, until one fits the network
    last_exception = None
    for dshape in data_shapes:
        h, w, c = dshape
        if layout == 'HWC':  # 보통 HWC(opencv)형식이다.
            x = mx.nd.zeros((1, h, w, c), ctx=ctx)
        elif layout == 'CHW':
            x = mx.nd.zeros((1, c, h, w), ctx=ctx)

        # hybridize and forward once
        wrapper_block.hybridize()
        try:
            wrapper_block(x)
            if path != None:
                wrapper_block.export(path, epoch, remove_amp_cast=remove_amp_cast)
            last_exception = None
            break
        except MXNetError as e:
            last_exception = e
    if last_exception is not None:
        raise RuntimeError(str(last_exception).splitlines()[0])
    return wrapper_block


# detector block + prediction block for mxnet c++
class PostNet(HybridBlock):

    def __init__(self, net=None, auxnet=None):
        super(PostNet, self).__init__()
        self._net = net
        self._auxnet = auxnet

    def hybrid_forward(self, F, x):
        cls_preds, box_preds, anchors = self._net(x)
        return self._auxnet(cls_preds, box_preds, anchors)


class ConvPredictor(HybridBlock):

    def __init__(self, num_channel=None,
                 kernel=(3, 3),
                 pad=(1, 1),
                 stride=(1, 1),
                 activation=None,
                 use_bias=False,
                 in_channels=0,
                 weight_initializer="zeros",
                 bias_initializer='zeros'):
        super(ConvPredictor, self).__init__()
        with self.name_scope():
            self.predictor = Conv2D(
                num_channel, kernel, strides=stride, padding=pad,
                activation=activation, use_bias=use_bias, in_channels=in_channels,
                weight_initializer=weight_initializer,
                bias_initializer=bias_initializer)

    def hybrid_forward(self, F, x):
        return self.predictor(x)


class EfficientNet_Except_Anchor(HybridBlock):

    def __init__(self, version=0,
                 input_size=(512, 512),
                 anchor_size_ratios=[1, pow(2, 1 / 3), pow(2, 2 / 3)],
                 anchor_aspect_ratios=[0.5, 1, 2],
                 num_classes=1,
                 ctx=mx.cpu()):
        super(EfficientNet_Except_Anchor, self).__init__()

        if version not in [0, 1, 2, 3, 4, 5, 6]:
            raise ValueError

        feature_sizes = []
        fpn_output = get_bifpn(version, ctx=mx.cpu(), dummy=True)(
            mx.nd.random_uniform(low=0, high=1, shape=(1, 3, input_size[0], input_size[1]), ctx=mx.cpu()))
        for fpn in fpn_output:
            feature_sizes.append(fpn.shape[2:])  # h, w

        self._bifpn = get_bifpn(version, ctx=ctx)
        self._num_classes = num_classes

        with self.name_scope():

            self._class_subnet = HybridSequential()
            self._box_subnet = HybridSequential()
            for _ in range(3):
                self._class_subnet.add(ConvPredictor(num_channel=256,
                                                     kernel=(3, 3),
                                                     pad=(1, 1),
                                                     stride=(1, 1),
                                                     activation='relu',
                                                     use_bias=True,
                                                     in_channels=0,
                                                     weight_initializer=mx.init.Normal(0.01),
                                                     bias_initializer='zeros'
                                                     ))
                self._box_subnet.add(ConvPredictor(num_channel=256,
                                                   kernel=3,
                                                   pad=1,
                                                   stride=1,
                                                   activation='relu',
                                                   use_bias=True,
                                                   in_channels=0,
                                                   weight_initializer=mx.init.Normal(0.01),
                                                   bias_initializer='zeros'
                                                   ))

            '''
            bias_initializer=mx.init.Constant(-np.log((1-0.01)/0.01)?
            논문에서,
             For the final convlayer of the classification subnet, we set the bias initialization to 
             b = − log((1 − π)/π), where π specifies that at that at the start of training every anchor should be 
             labeled as foreground with confidence of ∼π. We use π = .01 in all experiments, 
             although results are robust to the exact value. As explained in section 3.3, 
             this initialization prevents the large number of background anchors from generating a large, 
             destabilizing loss value in the first iteration of training.

             -> 초기에 class subnet 마지막 bias를 b = − log((1 − π)/π)로 설정함으로써, 
             모든  anchor를 0.01 값을 가지는 foreground로 만들어버리는 초기화 방법
             거의 대부분인 background anchor가 첫 번째 학습에서 불안정한 loss 값을 가지는 것을 방지해준다함.
            '''
            prior = 0.01
            self._class_subnet.add(
                ConvPredictor(num_channel=num_classes * len(anchor_size_ratios) * len(anchor_aspect_ratios),
                              kernel=(3, 3),
                              pad=(1, 1),
                              stride=(1, 1),
                              activation=None,
                              use_bias=True,
                              in_channels=0,
                              weight_initializer=mx.init.Normal(0.01),
                              bias_initializer=mx.init.Constant(-np.log((1 - prior) / prior))
                              ))

            self._box_subnet.add(ConvPredictor(num_channel=4 * len(anchor_size_ratios) * len(anchor_aspect_ratios),
                                               kernel=3,
                                               pad=1,
                                               stride=1,
                                               activation=None,
                                               use_bias=True,
                                               in_channels=0,
                                               weight_initializer=mx.init.Normal(0.01),
                                               bias_initializer='zeros'
                                               ))

        self._class_subnet.initialize(ctx=ctx)
        self._box_subnet.initialize(ctx=ctx)
        print(f"{self.__class__.__name__} Head weight init 완료")

    def hybrid_forward(self, F, x):

        # class, box prediction
        # self._fpn_resnet(x)  # p3, p4, p5, p6, p7
        # (batch, height, width, class) -> (batch, -1)
        cls_preds = [F.flatten(data=F.transpose(data=self._class_subnet(fpn_feature), axes=(0, 2, 3, 1)))
                     for fpn_feature in self._bifpn(x)]
        # (batch, height, width, 4) -> (batch, -1)
        box_preds = [F.flatten(data=F.transpose(data=self._box_subnet(fpn_feature), axes=(0, 2, 3, 1)))
                     for fpn_feature in self._bifpn(x)]

        cls_preds = F.reshape(data=F.concat(*cls_preds, dim=-1), shape=(0, -1, self._num_classes))
        box_preds = F.reshape(data=F.concat(*box_preds, dim=-1), shape=(0, -1, 4))

        return cls_preds, box_preds


class EfficientAnchorGenerator(HybridBlock):

    def __init__(self, index=0,
                 input_size=(512, 512),
                 feature_size=(64, 64),
                 anchor_size=32,
                 anchor_size_ratios=[1, pow(2, 1 / 3), pow(2, 2 / 3)],
                 anchor_aspect_ratios=[0.5, 1, 2],
                 box_offset=(0.5, 0.5), box_clip=False):
        super(EfficientAnchorGenerator, self).__init__()
        self._height = input_size[0]
        self._width = input_size[1]
        self._box_clip = box_clip

        # 아래와 같이 등록해주면 hybrid_forward에 anchors로서 들어감
        with self.name_scope():
            self.anchors = self.params.get_constant(name=f'anchor_{index}',
                                                    value=self._generate_anchors(feature_size=feature_size,
                                                                                 anchor_size=anchor_size,
                                                                                 anchor_size_ratios=anchor_size_ratios,
                                                                                 anchor_aspect_ratios=anchor_aspect_ratios,
                                                                                 box_offset=box_offset))

    def _generate_anchors(self, feature_size=None, anchor_size=None, anchor_size_ratios=None, anchor_aspect_ratios=None,
                          box_offset=None):
        # cx, xy, w, h 순으로 붙임!!!
        step_y = self._height / feature_size[0]
        step_x = self._width / feature_size[1]
        anchor_size_ratios_width = np.multiply(anchor_size, np.array(anchor_size_ratios))
        anchor_size_ratios_height = np.multiply(anchor_size, np.array(anchor_size_ratios))

        anchors = []
        for y in range(feature_size[0]):
            for x in range(feature_size[1]):
                for nasr_w, nasr_h in zip(anchor_size_ratios_width, anchor_size_ratios_height):
                    cy = (y + box_offset[0]) * step_y
                    cx = (x + box_offset[1]) * step_x
                    for asr in anchor_aspect_ratios:
                        sr = np.sqrt(asr)
                        w = nasr_w * sr
                        h = nasr_h / sr
                        anchors.append([cx, cy, w, h])
        anchors = np.array(anchors)
        if self._box_clip:
            cx, cy, w, h = np.split(anchors, 4, axis=-1)
            anchors = np.concatenate([np.clip(cx, 0, self._width),
                                      np.clip(cy, 0, self._height),
                                      np.clip(w, 0, self._width),
                                      np.clip(h, 0, self._height),
                                      ], axis=-1)
        return anchors

    def hybrid_forward(self, F, x, anchors):
        anchors = F.identity(anchors)
        return anchors


class AnchorNet(HybridBlock):

    def __init__(self, net=None, version=None, target_size=None,
                 anchor_sizes=[32, 64, 128, 256, 512],
                 anchor_size_ratios=[1, pow(2, 1 / 3), pow(2, 2 / 3)],
                 anchor_aspect_ratios=[0.5, 1, 2],
                 box_offset=(0.5, 0.5),
                 anchor_box_clip=True, ctx=mx.cpu()):
        super(AnchorNet, self).__init__()

        self._net = net
        if version not in [0, 1, 2, 3, 4, 5, 6]:
            raise ValueError

        feature_sizes = []
        bifpn = get_bifpn(version, ctx=mx.cpu(), dummy=True)(
            mx.nd.random_uniform(low=0, high=1, shape=(1, 3, target_size[0], target_size[1]), ctx=mx.cpu()))
        for bif in bifpn:
            feature_sizes.append(bif.shape[2:])  # h, w

        # get_fpn_resnet 외부에서 보내지 않으면. 무조건 forward 한번 시켜야 하는데,
        # 네트워크를 정확히 정의 해놓지 않아서...(default init) 쓸데 없는 코드를
        # 넣어야 한다.
        with self.name_scope():

            # 아래 두줄은 self.name_scope()안에 있어야 한다. - 새롭게 anchor만드는 네크워크를 생성하는 것이므로.!!!
            # self.name_scope() 밖에 있으면 기존의 self._net 과 이름이 겹친다.

            self._bifpn = get_bifpn(version, ctx=ctx, dummy=True)
            self._bifpn.forward(mx.nd.ones(shape=(1, 3) + target_size, ctx=ctx))
            self._anchor_generators = HybridSequential()

            for index, feature_size, anchor_size in zip(range(len(feature_sizes)), feature_sizes, anchor_sizes):
                self._anchor_generators.add(EfficientAnchorGenerator(index=index,
                                                                     input_size=target_size,
                                                                     feature_size=feature_size,
                                                                     anchor_size=anchor_size,
                                                                     anchor_size_ratios=anchor_size_ratios,
                                                                     anchor_aspect_ratios=anchor_aspect_ratios,
                                                                     box_offset=box_offset,
                                                                     box_clip=anchor_box_clip))

        self._anchor_generators.initialize(ctx=ctx)

    def hybrid_forward(self, F, x):
        cls_preds, box_preds = self._net(x)
        anchors = [anchor_generator(bifpn_feature) for bifpn_feature, anchor_generator in
                   zip(self._bifpn(x), self._anchor_generators)]
        anchors = F.reshape(F.concat(*anchors, dim=0), shape=(1, -1, 4))
        return cls_preds, box_preds, anchors
