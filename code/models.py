from dataloader import *
import torch.nn.functional as F


# Defining the fnet model for image warping
def down_block(inputs, output_channel=64, stride=1):
    net = nn.Sequential(conv2(inputs, 3, output_channel, stride, use_bias=True), lrelu(0.2),
                        conv2(output_channel, 3, output_channel, stride, use_bias=True)
                        , lrelu(0.2), maxpool())

    return net


def up_block(inputs, output_channel=64, stride=1):
    net = nn.Sequential(conv2(inputs, 3, output_channel, stride, use_bias=True), lrelu(0.2),
                        conv2(output_channel, 3, output_channel, stride, use_bias=True)
                        , lrelu(0.2), nn.Upsample(scale_factor=2, mode="bilinear"))

    return net


class f_net(nn.Module):
    def __init__(self):
        super(f_net, self).__init__()
        self.down1 = down_block(3, 32)
        self.down2 = down_block(32, 64)
        self.down3 = down_block(64, 128)
        self.down4 = down_block(128, 256)

        self.up1 = up_block(256, 512)
        self.up2 = up_block(512, 256)
        self.up3 = up_block(256, 128)
        self.up4 = up_block(128, 64)

        self.output_block = nn.Sequential(conv2(64, 3, 32, 1), lrelu(0.2), conv2(32, 3, 2, 1))

    def forward(self, x):
        net = self.down1(x)
        net = self.down2(net)
        net = self.down3(net)
        net = self.down4(net)
        net = self.up1(net)
        net = self.up2(net)
        net = self.up3(net)
        net = self.up4(net)

        net = self.output_block(net)
        net = torch.tanh(net) * 24.0

        return net


# Defining the generator to upscale images
def residual_block(inputs, output_channel=64, stride=1):
    net = nn.Sequential(conv2(inputs, 3, output_channel, stride, use_bias=True), nn.ReLU(),
                        conv2(output_channel, 3, output_channel, stride, use_bias=False))

    return net


class generator(nn.Module):
    def __init__(self, gen_output_channels, args=None):
        super(generator, self).__init__()

        if args is None:
            raise ValueError("No args is provided for generator")

        self.conv = nn.Sequential(conv2(51, 3, 64, 1), nn.ReLU())
        self.num = args.num_resblock
        self.resids = nn.ModuleList([residual_block(64, 64, 1) for i in range(self.num)])

        self.conv_trans = nn.Sequential(conv2_tran(64, 3, 128, stride=2, output_padding=1), nn.ReLU()
                                        , conv2_tran(128, 3, 128, stride=2, output_padding=1), nn.ReLU(),
                                        conv2(128, 3, 64, 1), nn.ReLU())
        self.output = conv2(64, 3, gen_output_channels, 1)

    def forward(self, x):
        net = self.conv(x)

        for i in range(self.num):
            net = self.resids[i](net) + net
        net = self.conv_trans(net)
        net = self.output(net)

        #low_res_in = x[:, 0:3, :, :]
        #bicubic_hi = bicubic_four(low_res_in)
        net = net #+ bicubic_hi
        return net


# Defining the discriminator for adversarial part
def discriminator_block(inputs, output_channel, kernel_size, stride):
    net = nn.Sequential(conv2(inputs, kernel_size, output_channel, stride, use_bias=False),
                        batchnorm(output_channel, is_training=True),
                        lrelu(0.2))
    return net


class discriminator(nn.Module):
    def __init__(self, args=None):
        super(discriminator, self).__init__()
        if args is None:
            raise ValueError("No args is provided for discriminator")

        self.conv = nn.Sequential(conv2(27, 3, 64, 1), lrelu(0.2))

        # block1
        self.block1 = discriminator_block(64, 64, 4, 2)

        # block2
        self.block2 = discriminator_block(64, 64, 4, 2)

        # block3
        self.block3 = discriminator_block(64, 128, 4, 2)

        # block4
        self.block4 = discriminator_block(128, 256, 4, 2)

        self.block5 = discriminator_block(256, 256, 4, 2)

        self.resid1 = residual_block(256, 256, 1)
        self.bn1 = batchnorm(256, True)
        self.resid2 = residual_block(256, 256, 1)
        self.bn2 = batchnorm(256, True)
        self.resid3 = residual_block(256, 128, 1)
        self.bn3 = batchnorm(128, True)
        self.resid4 = residual_block(128, 128, 1)
        self.bn4 = batchnorm(128, True)
        self.resid5 = residual_block(128, 3, 1)
        self.bn5 = batchnorm(3, True)
        self.relu = lrelu(0.2)
        self.fc = denselayer(48, 1)

    def forward(self, x):
        layer_list = []
        net = self.conv(x)
        net = self.block1(net)
        layer_list.append(net)
        net = self.block2(net)
        layer_list.append(net)
        net = self.block3(net)
        layer_list.append(net)
        net = self.block4(net)
        layer_list.append(net)
        net = self.block5(net)
        layer_list.append(net)
        net = self.bn1(self.resid1(net) + net)
        net = self.relu(net)
        net = self.bn2(self.resid2(net) + net)
        net = self.relu(net)
        net = self.bn3(self.resid3(net))
        net = self.relu(net)
        net = self.bn4(self.resid4(net) + net)
        net = self.relu(net)
        net = self.bn5(self.resid5(net))
        net = self.relu(net)
        net = net.view(net.shape[0], -1)
        net = self.fc(net)
        net = torch.sigmoid(net)
        return net, layer_list