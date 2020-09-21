
import os, sys
import argparse
import time
import random
import cv2
import numpy as np
import torch
import torch.nn as nn
#import torchvision
#import torchvision.transforms as transforms
from torch.utils.data import Dataset, DataLoader, TensorDataset, random_split

import nsml
from nsml.constants import DATASET_PATH, GPU_NUM

from torch.utils.data import Dataset, DataLoader

from PIL import Image
from collections import defaultdict
from sklearn.model_selection import train_test_split

from efficientnet_pytorch import EfficientNet

import argparse
from random import uniform
from imgaug import augmenters as iaa


IMSIZE = 120, 60
VAL_RATIO = 0.2

# Seed
RANDOM_SEED = 44
torch.manual_seed(RANDOM_SEED)
torch.cuda.manual_seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

def bind_model(model):
    def save(dir_name):
        os.makedirs(dir_name, exist_ok=True)
        torch.save(model.state_dict(), os.path.join(dir_name, 'model'))
        print('model saved!')

    def load(dir_name):
        model.load_state_dict(torch.load(os.path.join(dir_name, 'model')))
        model.eval()
        print('model loaded!')

    def infer(data):  ## test mode
        X = ImagePreprocessing(data)
        X = np.array(X)
        X = np.expand_dims(X, axis=1)
        ##### DO NOT CHANGE ORDER OF TEST DATA #####
        with torch.no_grad():
            X = torch.from_numpy(X).float().to(device)
            pred = model.forward(X)
            prob, pred_cls = torch.max(pred, 1)
            pred_cls = pred_cls.tolist()
            #pred_cls = pred_cls.data.cpu().numpy()
        print('Prediction done!\n Saving the result...')
        return pred_cls

    nsml.bind(save=save, load=load, infer=infer)


def image_padding(img_whole):
    img = np.zeros((600,600))
    h, w = img_whole.shape

    if (600 - h) != 0:
        gap = int((600 - h)/2)
        img[gap:gap+h,:] = img_whole
    elif (600 - w) != 0:
        gap = int((600 - w)/2)
        img[:,gap:gap+w] = img_whole
    else:
        img = img_whole

    return img

def DataLoad(imdir):
    impath = [os.path.join(dirpath, f) for dirpath, dirnames, files in os.walk(imdir) for f in files if all(s in f for s in ['.jpg'])]
    l_img_list = defaultdict(list)
    r_img_list = defaultdict(list)

    print('Loading', len(impath), 'images ...')

    for i, p in enumerate(impath):
        img_whole = cv2.imread(p, 0)
        # zero padding
        img_whole = image_padding(img_whole)
        h, w = img_whole.shape
        h_, w_ = h, w//2
        l_img = img_whole[:, :w_]
        r_img = img_whole[:, w_:2*w_]
        _, l_cls, r_cls = os.path.basename(p).split('.')[0].split('_')
        if l_cls=='0' or l_cls=='1' or l_cls=='2' or l_cls=='3':
            l_img_list[int(l_cls)].append(l_img)
        if r_cls=='0' or r_cls=='1' or r_cls=='2' or r_cls=='3':
            r_img_list[int(r_cls)].append(r_img)
    
    r_img_train, l_img_train = [],[]
    r_img_val, l_img_val = [],[]
    r_lb_train, l_lb_train = [],[]
    r_lb_val, l_lb_val = [],[]

    for i in range(0,4):
        img_train,img_val, label_train, label_val = train_test_split(l_img_list[i],[i]*len(l_img_list[i]),test_size=0.2,shuffle=True,random_state=13241)
        
        l_img_train += img_train
        l_img_val += img_val
        l_lb_train += label_train
        l_lb_val += label_val

        img_train,img_val, label_train,label_val = train_test_split(r_img_list[i],[i]*len(r_img_list[i]),test_size=0.2,shuffle=True,random_state=13241)
        
        r_img_train += img_train
        r_img_val += img_val
        r_lb_train += label_train
        r_lb_val += label_val

    print(len(r_img_train)+len(l_img_train), 'Train data with label 0-3 loaded!')
    print(len(l_img_val)+len(r_img_val), 'Validation data with label 0-3 loaded!')


    return l_img_train,l_lb_train,l_img_val,l_lb_val,r_img_train,r_lb_train,r_img_val,r_lb_val


def ImagePreprocessing(img):
    # 자유롭게 작성
    h, w = IMSIZE
    print('Preprocessing ...')
    for i, im, in enumerate(img):
        tmp = cv2.resize(im, dsize=(w, h), interpolation=cv2.INTER_AREA)
        tmp = tmp / 255.
        img[i] = tmp
    print(len(img), 'images processed!')
    return img


class Sdataset(Dataset):
    def __init__(self, images, labels, args, augmentation, left=True):
        self.images = images
        self.labels = labels
        self.args = args
        self.augmentation = augmentation
        self.left = left
        if not left:
            self.right2left()
        print ("images:", len((self.images)), "#labels:", len((self.labels)))

    def right2left():
        imglist = []
        for img in self.images:
            imglist.append(cv2.flip(img, 0))
        self.images = imglist
    
    def box_crop(self, img):
        half_size = self.args.img_size//2

        if self.augmentation:
            x_margin = int(half_size * uniform(1.0, 1.0+self.args.x_trans_factor))
            y_margin = int(half_size * uniform(1.0-self.args.y_trans_factor, 1.0 + self.args.y_trans_factor))
            center_point = (300-x_margin, 300+y_margin)
        else:
            x_margin = half_size
            center_point = (300-x_margin, 300)

        img_box = img[center_point[1]-half_size:center_point[1]+half_size,
                      center_point[0]-half_size:center_point[0]+half_size]

        return img_box

    def augment_img(self, img):
        scale_factor = uniform(1-self.args.scale_factor, 1+self.args.scale_factor)
        rot_factor = uniform(-self.args.rot_factor, self.args.rot_factor)

        seq = iaa.Sequential([
                iaa.Affine(
                    scale=(scale_factor, scale_factor),
                    rotate=rot_factor
                )
            ])

        seq_det = seq.to_deterministic()
        img = seq_det.augment_images(img)

        return img

    def __getitem__(self, index):
        image = self.images[index]
        img_box = self.box_crop(image)

        if self.augmentation:
            img_box = self.augment_img(img_box)

        img_box = img_box[None, ...]

        img_box = torch.tensor(img_box).float()

        label = self.labels[index]
        
        return {"image": img_box, "label": label} 

    def __len__(self):
        return len(self.labels)

def get_current_lr(optimizer):
    return optimizer.state_dict()['param_groups'][0]['lr']

def lr_update(epoch, args, optimizer):
    prev_lr = get_current_lr(optimizer)
    if (epoch + 1) in args.lr_decay_epoch:
        for param_group in optimizer.param_groups:
            param_group['lr'] = (prev_lr * 0.1)
            print("LR Decay : %.7f to %.7f" % (prev_lr, prev_lr * 0.1))

def ParserArguments():
    args = argparse.ArgumentParser()

    # Setting Hyperparameters
    args.add_argument('--epoch', type=int, default=80)          # epoch 수 설정
    args.add_argument('--batch_size', type=int, default=8)      # batch size 설정
    args.add_argument('--learning_rate', type=float, default=1e-4)  # learning rate 설정
    args.add_argument('--lr_decay_epoch', type=str, default='50,70')  # learning rate 설정
    args.add_argument('--num_classes', type=int, default=4)     # 분류될 클래스 수는 4개

    # Network
    args.add_argument('--network', type=str, default='efficientb4')          # epoch 수 설정
    args.add_argument('--resume', type=str, default='weights/efficient-b4.pth')          # epoch 수 설정

    # Augmentation
    args.add_argument('--x_trans_factor', type=float, default=0.1)
    args.add_argument('--y_trans_factor', type=float, default=0.1)
    args.add_argument('--rot_factor', type=float, default=30)          # epoch 수 설정
    args.add_argument('--scale_factor', type=float, default=0.15)          # epoch 수 설정


    # DO NOT CHANGE (for nsml)
    args.add_argument('--mode', type=str, default='train', help='submit일 때 test로 설정됩니다.')
    args.add_argument('--iteration', type=str, default='0',
                      help='fork 명령어를 입력할때의 체크포인트로 설정됩니다. 체크포인트 옵션을 안주면 마지막 wall time 의 model 을 가져옵니다.')
    args.add_argument('--pause', type=int, default=0, help='model 을 load 할때 1로 설정됩니다.')

    args = args.parse_args()
    args.lr_decay_epoch = map(int, args.lr_decay_epoch.split(','))
    return args

if __name__ == '__main__':
    print(GPU_NUM)
    args = ParserArguments()

    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

    #####   Model   #####
    model = EfficientNet.from_name('efficientnet-b4')
    if os.path.exists(args.resume):
        model.load_state_dict(torch.load(args.resume))
    model._fc = nn.Linear(model._fc.in_features, args.num_classes)

    #model.double()
    model.to(device)
    class_weights = torch.Tensor([1/0.78, 1/0.13, 1/0.06, 1/0.03])
    criterion = nn.CrossEntropyLoss(class_weights).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, momentum=0.9)
    #optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    bind_model(model)

    if args.ifpause:  ## for test mode
        print('Inferring Start ...')
        nsml.paused(scope=locals())

    if args.ifmode == 'train':  ## for train mode
        print('Training start ...')
        # 자유롭게 작성
        images, labels = DataLoad(imdir=os.path.join(DATASET_PATH, 'train'))
        images = ImagePreprocessing(images)
        images = np.array(images)
        images = np.expand_dims(images, axis=1)
        labels = np.array(labels)

        dataset = TensorDataset(torch.from_numpy(images).float(), torch.from_numpy(labels).long())
        subset_size = [len(images) - int(len(images) * VAL_RATIO),int(len(images) * VAL_RATIO)]
        tr_set, val_set = random_split(dataset, subset_size)
        batch_train = DataLoader(tr_set, batch_size=args.batch_size, shuffle=True)
        batch_val = DataLoader(val_set, batch_size=1, shuffle=False)

        #####   Training loop   #####
        STEP_SIZE_TRAIN = len(images) // args.batch_size
        print('\n\n STEP_SIZE_TRAIN= {}\n\n'.format(STEP_SIZE_TRAIN))
        t0 = time.time()
        for epoch in range(args.nb_epoch):
            t1 = time.time()
            print('Model fitting ...')
            print('epoch = {} / {}'.format(epoch + 1, args.nb_epoch))
            print('check point = {}'.format(epoch))
            a, a_val, tp, tp_val = 0, 0, 0, 0
            for i, (x_tr, y_tr) in enumerate(batch_train):
                x_tr, y_tr = x_tr.to(device), y_tr.to(device)
                optimizer.zero_grad()
                pred = model(x_tr)
                loss = criterion(pred, y_tr)
                loss.backward()
                optimizer.step()
                prob, pred_cls = torch.max(pred, 1)
                a += y_tr.size(0)
                tp += (pred_cls == y_tr).sum().item()

            with torch.no_grad():
                for j, (x_val, y_val) in enumerate(batch_val):
                    x_val, y_val = x_val.to(device), y_val.to(device)
                    pred_val = model(x_val)
                    loss_val = criterion(pred_val, y_val)
                    prob_val, pred_cls_val = torch.max(pred_val, 1)
                    a_val += y_val.size(0)
                    tp_val += (pred_cls_val == y_val).sum().item()

            acc = tp / a
            acc_val = tp_val / a_val
            print("  * loss = {}\n  * acc = {}\n  * loss_val = {}\n  * acc_val = {}".format(loss.item(), acc, loss_val.item(), acc_val))
            nsml.report(summary=True, step=epoch, epoch_total=args.nb_epoch, loss=loss.item(), acc=acc, val_loss=loss_val.item(), val_acc=acc_val)
            nsml.save(epoch)
            print('Training time for one epoch : %.1f\n' % (time.time() - t1))

            lr_update(epoch, args, optimizer)
        print('Total training time : %.1f' % (time.time() - t0))