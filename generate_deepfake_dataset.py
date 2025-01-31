'''
Author: Naiyuan liu
Github: https://github.com/NNNNAI
Date: 2021-11-23 17:03:58
LastEditors: Naiyuan liu
LastEditTime: 2021-11-24 19:19:26
Description: 
'''

import cv2
import torch
import fractions
import numpy as np
from PIL import Image
import torch.nn.functional as F
from torchvision import transforms
from models.models import create_model
from options.test_options import TestOptions
from insightface_func.face_detect_crop_multi import Face_detect_crop
from util.reverse2original import reverse2wholeimage
import os
from util.add_watermark import watermark_image
from util.norm import SpecificNorm
from parsing_model.model import BiSeNet
from tqdm import tqdm

def lcm(a, b): return abs(a * b) / fractions.gcd(a, b) if a and b else 0

transformer_Arcface = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

def _totensor(array):
    tensor = torch.from_numpy(array)
    img = tensor.transpose(0, 1).transpose(0, 2).contiguous()
    return img.float().div(255)

if __name__ == '__main__':
    opt = TestOptions().parse()

    start_epoch, epoch_iter = 1, 0
    crop_size = opt.crop_size

    torch.nn.Module.dump_patches = True
    if crop_size == 512:
        opt.which_epoch = 550000
        opt.name = '512'
        mode = 'ffhq'
    else:
        mode = 'None'
    logoclass = watermark_image('./simswaplogo/simswaplogo.png')
    model = create_model(opt)
    model.eval()
    spNorm =SpecificNorm()

    app = Face_detect_crop(name='antelope', root='./insightface_func/models')
    app.prepare(ctx_id= 0, det_thresh=0.6, det_size=(640,640),mode=mode)

    pic_b = opt.pic_b_path
    dataset_types = os.listdir(os.path.join(pic_b, "images"))
    name_txt_path = os.path.join(opt.output_path, "names.txt")
    name_txt_file = open(name_txt_path, "w")

    with torch.no_grad():
        pic_a = opt.pic_a_path
        img_a_whole = cv2.imread(pic_a)
        img_a_align_crop, _, _ = app.get(img_a_whole, crop_size)
        img_a_align_crop_pil = Image.fromarray(cv2.cvtColor(img_a_align_crop[0], cv2.COLOR_BGR2RGB))
        img_a = transformer_Arcface(img_a_align_crop_pil)
        img_id = img_a.view(-1, img_a.shape[0], img_a.shape[1], img_a.shape[2])
        img_id = img_id.cuda()
        img_id_downsample = F.interpolate(img_id, size=(112, 112))
        latend_id = model.netArc(img_id_downsample)
        latend_id = F.normalize(latend_id, p=2, dim=1)

        for dataset_type in dataset_types:
            image_dir = os.path.join(pic_b, "images", dataset_type)
            output_image_dir = os.path.join(opt.output_path, "images", dataset_type)
            output_label_dir = os.path.join(opt.output_path, "labels", dataset_type)
            if not os.path.exists(output_image_dir):
                os.makedirs(output_image_dir)
            if not os.path.exists(output_label_dir):
                os.makedirs(output_label_dir)
            image_names = sorted(os.listdir(image_dir))
            progress_bar = tqdm(enumerate(image_names), total=len(image_names))
            for i, image_name in progress_bar:
                try:
                    image_path = os.path.join(image_dir, image_name)
                    label_path = os.path.join(output_label_dir, image_name.replace(".jpg", ".txt"))

                    img_b_whole = cv2.imread(image_path)

                    result = app.get(img_b_whole, crop_size)

                    img_b_align_crop_list, b_mat_list, bboxes = result
                    with open(label_path, "w") as f:
                        for b, box in enumerate(bboxes):
                            image_width = img_b_whole.shape[1]
                            image_height = img_b_whole.shape[0]
                            x1, y1, x2, y2, score = box

                            x_center = (x1 + x2) / 2.0
                            y_center = (y1 + y2) / 2.0
                            width = x2 - x1
                            height = y2 - y1

                            x_center /= image_width
                            y_center /= image_height
                            width /= image_width
                            height /= image_height

                            if (b+1) == len(bboxes):
                                f.write(f"{0} {x_center} {y_center} {width} {height}")
                            else:
                                f.write(f"{0} {x_center} {y_center} {width} {height}\n")
                        f.close()

                    swap_result_list = []
                    b_align_crop_tenor_list = []

                    for b_align_crop in img_b_align_crop_list:
                        b_align_crop_tenor = _totensor(cv2.cvtColor(b_align_crop,cv2.COLOR_BGR2RGB))[None,...].cuda()

                        swap_result = model(None, b_align_crop_tenor, latend_id, None, True)[0]
                        swap_result_list.append(swap_result)
                        b_align_crop_tenor_list.append(b_align_crop_tenor)


                    if opt.use_mask:
                        n_classes = 19
                        net = BiSeNet(n_classes=n_classes)
                        net.cuda()
                        save_pth = os.path.join('./parsing_model/checkpoint', '79999_iter.pth')
                        net.load_state_dict(torch.load(save_pth))
                        net.eval()
                    else:
                        net =None

                    output_path = os.path.join(output_image_dir, image_name)
                    reverse2wholeimage(b_align_crop_tenor_list,swap_result_list, b_mat_list, crop_size, img_b_whole, logoclass, \
                        output_path, opt.no_simswaplogo,pasring_model =net,use_mask=opt.use_mask, norm = spNorm)
                except:
                    name_txt_file.write(f"{image_name}\n")
                    print(f"pass {image_name}")
            progress_bar.close()
        print('************ Done ! ************')
        name_txt_file.close()
