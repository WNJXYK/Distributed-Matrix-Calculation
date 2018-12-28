# 分布式矩阵运算

这是一个使用Python3.6编写的简单的分布式矩阵计算的测试程序，支持分布式矩阵乘法与分布式矩阵求逆。整个项目使用Docker封装，容易批量配置。矩阵乘法使用分块乘法实现分布式，矩阵求逆使用分块消元算法实现分布式，仅仅实现功能，在网络传输、性能与并行度上依旧有所不足。

* `multiprocessing` 实现分布式的任务分配
* `flask` 实现Web控制界面
* `h5py` 实现结果HDF5格式存储

已发布到Docker Hub：(https://hub.docker.com/r/wnjxyk/simple_distributed_matrix)[https://hub.docker.com/r/wnjxyk/simple_distributed_matrix]，可以在这个网址拉取镜像并且测试。

## 如何使用

1. 首先从镜像仓库拉取本镜像。
```shell
docker pull wnjxyk/simple_distributed_matrix
```

2. 从镜像新建了若干容器，例如如下代码：创建5个容器，分别映射端口号为8080、8081～8084。这里8080作为主控节点，8081～8084作为分布式计算节点。
```shell
docker run -d -it -p 8080:80 matrix python /root/Distributed_Matrix_Method/Distributed.py
docker run -d -it -p 8081:80 --cpus=0.01 matrix python /root/Distributed_Matrix_Method/Distributed.py
docker run -d -it -p 8082:80 --cpus=0.01 matrix python /root/Distributed_Matrix_Method/Distributed.py
docker run -d -it -p 8083:80 --cpus=0.01 matrix python /root/Distributed_Matrix_Method/Distributed.py
docker run -d -it -p 8084:80 --cpus=0.01 matrix python /root/Distributed_Matrix_Method/Distributed.py
```

3. 浏览器中打开`0.0.0.0:8080`的控制页面，开始控制节点。然后进入`0.0.0.0:8081~0.0.0.0:8084`的控制页面，设置控制节点IP与端口，将计算节点连接到控制节点。

4. 返回控制节点控制页面，可以自动矩阵的大小与分块大小进行矩阵乘法与求逆操作，任务完成后可以下载HDF5格式文件核对是否计算正确（系统也会自动核对，显示为Correct即为正确）。
![One Worker Result](https://raw.githubusercontent.com/WNJXYK/Distributed-Matrix-Calculation/master/Doc/OneResult.png)


## 效果测试
效果测试可以参考Doc目录下的简易描述：(Doc)[https://github.com/WNJXYK/Distributed-Matrix-Calculation/blob/master/Doc/Docker.md]