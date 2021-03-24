import os
import json
import uuid
import oss2
import time
import base64
import string
import random
import logging
import requests
import muggle_ocr
from urllib import parse
from pyDes import des, CBC, PAD_PKCS5
from tenacity import retry, wait_random, wait_fixed, retry_if_exception_type, stop_after_attempt
os.chdir(os.path.split(os.path.realpath(__file__))[0])
class DailyCP:
    def __init__(self):
        self.is_login=False
        self.logger=logging.getLogger(__name__)
        self.session=requests.session()
        formatter=logging.Formatter(fmt="%(asctime)s-%(levelname)s-%(message)s",datefmt="%Y-%m-%d %H:%M:%S")
        handler=logging.StreamHandler()
        handler.setFormatter(fmt=formatter)
        with open(file="config.json",mode="r",encoding="utf-8") as reader:
            self.conf=json.loads(reader.read())
        with open(file="apis.json",mode="r",encoding="utf-8") as reader:
            self.apis=json.loads(reader.read())
        if self.conf["debug"]==True:
            self.logger.setLevel(logging.DEBUG)
            handler.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
            handler.setLevel(logging.INFO)
        self.logger.addHandler(handler)
        default_header={
            "User-Agent":"Mozilla/5.0 (Linux; Android 10; BKL-AL20 Build/HUAWEIBKL-AL20; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/89.0.4389.90 Mobile Safari/537.36 okhttp/3.12.4",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest"
        }
        self.session.headers.update(default_header)
        json_resp=self.session.get(self.apis["list_addr"]).json()
        self.logger.debug("已获取学校信息")
        for data in json_resp["data"]:
            if data["name"]==self.conf["school"]:
                try:
                    self.login(data=data)
                except Exception as e:
                    self.logger.error("登陆过程出错，错误内容：%s" %e)
                    raise RuntimeError("登陆过程出错")
                else:
                    self.logger.info("登陆成功")
                    self.school_data=data
                break
        self.logger.debug("完成初始化")
        ext={
            "lon":self.conf["lon"],
            "model":"Huawei Honor View 10",
            "appVersion":self.apis["appVersion"],
            "systemVersion":"10.0",
            "userId":self.conf["username"],
            "systemName":"android",
            "lat":self.conf["lat"],
            "deviceId":str(uuid.uuid1())
        }
        self.logger.debug("生成信息：%s" %json.dumps(ext))
        self.submit_header={
            "CpdailyStandAlone":0,
            "extension":1,
            "Cpdaily-Extension":self.DESEncrypt(json.dumps(ext))
            }
    def captcha(self,data:dict,lt:str,ocr:bool=True):
        self.logger.info("正在处理验证码")
        img=self.session.get(data["idsUrl"]+"/generateCaptcha",params={"ltId":lt,"random":"".join(random.sample(string.ascii_letters+string.digits,32))}).content
        if ocr==False:
            with open(file="captcha.jfif",mode="wb") as writer:
                writer.write(img)
            self.logger.info("验证码图片已写入程序文件夹下的captcha.jfif文件，请进行人肉识别")
            captcha=input("请输入验证码：").strip()
        else:
            sdk=muggle_ocr.SDK(model_type=muggle_ocr.ModelType.Captcha)
            captcha=sdk.predict(image_bytes=img)
        return captcha
    @retry(wait=wait_fixed(2)+wait_random(0,3),retry=retry_if_exception_type(requests.exceptions.ConnectionError),stop=stop_after_attempt(5),reraise=True)
    def login(self,data:dict,ocr:bool=True):
        # data={"id":"","name":"","tenantCode":"","img":"","distance":"","dis":,"idsUrl":"","joinType":"","appId":"","casLoginUrl":"","isEnter":}
        self.logger.info("正在开始登陆")
        captcha=""
        failed=0
        if data["joinType"]=="CLOUD":
            self.logger.debug("学校 %s 支持CLOUD方式登陆" %data["name"])
            res=self.session.get(data["idsUrl"])
            params=parse.parse_qs(parse.urlparse(res.url).query)
            if len(params)==1:
                lt=params[list(params.keys())[0]][0]
                self.logger.debug("获取lt：%s" %lt)
            else:
                self.logger.debug("URL参数：%s" %params)
                raise RuntimeError("URL参数有误")
            self.session.headers.update({"Referer":res.url})
            while True:
                json_resp=self.session.post(data["idsUrl"]+"/security/lt",data={"lt":lt}).json()
                self.logger.debug("提交lt结果：%s" %json_resp)
                if json_resp["result"]["needCaptcha"]==True:
                    lt=json_resp["result"]["_lt"]
                    captcha=self.captcha(data=data,lt=lt,ocr=ocr)
                json_resp=self.session.post(data["idsUrl"]+"/doLogin",data={"username":self.conf["username"],"password":self.conf["password"],"mobile":"","captcha":captcha,"rememberMe":False,"lt":lt}).json()
                self.logger.debug("登陆信息：%s" %json_resp)
                if json_resp["resultCode"]=="REDIRECT":
                    self.session.headers.update({"Referer":"https://"+parse.urlparse(data["idsUrl"]).netloc+"/portal/index.html"})
                    json_resp=self.session.get(data["idsUrl"]+"/login",params={"service":"https://"+parse.urlparse(data["idsUrl"]).netloc+json_resp["url"]}).json()
                    self.logger.debug("登陆重定向数据：%s" %json_resp)
                    if json_resp["resultCode"]=="REDIRECT":
                        self.session.get(json_resp["url"])
                        self.is_login=True
                        break
                else:
                    self.logger.error("登陆失败，服务器数据：%s" %json_resp)
                    failed=failed+1
                    if failed>=3:
                        break
        elif data["joinType"]=="NOTCLOUD":
            self.logger.debug("学校 %s 支持NOTCLOUD方式登陆" %data["name"])

            self.is_login=True
        else:
            self.logger.error("学校 %s 不支持云登陆" %data["name"])
            raise RuntimeError("不支持云端登陆")
        self.session.headers.update({"User-Agent":self.session.headers["User-Agent"]+" cpdaily/%s wisedu/%s" %(self.apis["appVersion"],self.apis["appVersion"])})
        self.logger.debug("已更新伪装User-Agent")
    @retry(wait=wait_fixed(2)+wait_random(0,3),retry=retry_if_exception_type(requests.exceptions.ConnectionError),stop=stop_after_attempt(5),reraise=True)
    def sign(self):
        sign_data=self.conf["cpdaily"]["sign"]
        if sign_data["enabled"]==True and self.is_login==True:
            self.logger.info("正在开始签到")
            self.session.headers.update({'Accept': 'application/json, text/plain, */*',"Content-Type":"application/json;charset=UTF-8"})
            urls=parse.urlparse(self.school_data["idsUrl"])
            self.session.headers.update({"Referer":"https://"+urls.netloc+"/wec-counselor-sign-apps/stu/mobile/index.html"})
            json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-sign-apps/stu/sign/getStuSignInfosInOneDay",json={}).json()
            self.logger.debug("获取签到信息：%s" %json_resp)
            if json_resp["code"]!="0":
                self.logger.error("获取签到信息失败")
                raise RuntimeError("获取签到信息失败")
            unSignedTasks=json_resp["datas"]["unSignedTasks"]
            if len(unSignedTasks)==0:
                self.logger.info("无未完成的签到")
            else:
                for unSignedTask in unSignedTasks:
                    self.logger.debug("当前签到信息：%s" %unSignedTask)
                    self.logger.info("正在处理 %s，发布者：%s" %(unSignedTask["taskName"],unSignedTask["senderUserName"]))
                    rateSignDate=unSignedTask["rateSignDate"].split(" ")[0]
                    rateTaskBeginTime=time.mktime(time.strptime(rateSignDate+" "+unSignedTask["rateTaskBeginTime"],"%Y-%m-%d %H:%M"))
                    rateTaskEndTime=time.mktime(time.strptime(rateSignDate+" "+unSignedTask["rateTaskEndTime"],"%Y-%m-%d %H:%M"))
                    current_time=time.time()
                    if current_time>rateTaskEndTime:
                        self.logger.error("当前时间已超过 %s 的提交时间" %unSignedTask["taskName"])
                        continue
                    if current_time<rateTaskBeginTime:
                        self.logger.error("当前时间未到达 %s 的开放时间" %unSignedTask["taskName"])
                        continue
                    form_data=dict()
                    params={
                        "signInstanceWid":unSignedTask["signInstanceWid"],
                        "signWid":unSignedTask["signWid"]
                    }
                    json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-sign-apps/stu/sign/detailSignTaskInst",json=params).json()
                    self.logger.debug("获取详细签到信息：%s" %json_resp)
                    if json_resp["datas"]["isPhoto"]==1:
                        json_resp_=self.session.post("https://"+urls.netloc+"/wec-counselor-sign-apps/stu/sign/getStsAccess",json={}).json()
                        fileName=json_resp_["datas"]["fileName"]
                        bucket=oss2.Bucket(oss2.Auth(access_key_id=json_resp_["datas"]["accessKeyId"],access_key_secret=json_resp_["datas"]["accessKeySecret"]),endpoint=json_resp_["datas"]["endPoint"],bucket_name=json_resp_["datas"]["bucket"])
                        with open(file=self.conf["photo"],mode="rb") as reader:
                            pic=reader.read()
                        bucket.put_object(key=fileName,headers={"x-oss-security-token":json_resp_["datas"]["securityToken"]},data=pic)
                        res=bucket.sign_url(method="PUT",key=fileName,expires=60)
                        self.logger.debug("图片位置：%s" %res)
                        json_resp_=self.session.post("https://"+urls.netloc+"/wec-counselor-sign-apps/stu/sign/previewAttachment",json={"ossKey":fileName}).json()
                        form_data["signPhotoUrl"]=json_resp_["datas"]
                    else:
                        form_data["signPhotoUrl"]=""
                    if json_resp["datas"]["isNeedExtra"]==1:
                        extraFields=json_resp["datas"]["extraFields"]
                        defaults=sign_data["defaults"]
                        extraFieldItemValues=[]
                        for extraField in extraFields:
                            for default in defaults:
                                for extraFieldItem in extraField["extraFieldItems"]:
                                    if extraFieldItem["content"]==default["value"]:
                                        extraFieldItemValue={"extraFieldItemValue":default["value"],"extraFieldItemWid":extraFieldItem["wid"]}
                                        if extraFieldItem["isOtherItems"]==1:
                                            extraFieldItemValue["extraFieldItemValue"]=default["other"]
                                        extraFieldItemValues.append(extraFieldItemValue)
                        form_data["extraFieldItems"]=extraFieldItemValues
                    form_data["signInstanceWid"]=json_resp["datas"]["signInstanceWid"]
                    form_data["longitude"]=self.conf["lon"]
                    form_data["latitude"]=self.conf["lat"]
                    form_data["isMalposition"]=json_resp["datas"]["isMalposition"]
                    form_data["abnormalReason"]=self.conf["abnormalReason"]
                    form_data["position"]=self.conf["address"]
                    self.session.headers.update(self.submit_header)
                    json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-sign-apps/stu/sign/completeSignIn",json=form_data).json()
                    if json_resp["message"]=="SUCCESS":
                        msg="%s:今日校园签到提交成功" %time.strftime("%Y-%m-%d %H:%M:%S",time.localtime())
                        self.logger.info("提交签到问卷成功")
                        if self.conf["msg"]["qmsg"]!="":
                            self.session.post("https://qmsg.zendee.cn/send/%s" %self.conf["msg"]["qmsg"],params={"msg":msg})
                    else:
                        self.logger.error("提交失败，原因：%s" %json_resp["message"])
        elif sign_data["enabled"]==False:
            self.logger.info("未启用签到，跳过签到")
        else:
            self.logger.error("未登录账号")
            raise RuntimeError("未登录账号")
    @retry(wait=wait_fixed(2)+wait_random(0,3),retry=retry_if_exception_type(requests.exceptions.ConnectionError),stop=stop_after_attempt(5),reraise=True)
    def submit(self):
        submit_data=self.conf["cpdaily"]["submit"]
        if submit_data["enabled"]==True and self.is_login==True:
            self.logger.info("正在开始提交报告")
            self.session.headers.update({'Accept': 'application/json, text/plain, */*',"Content-Type":"application/json;charset=UTF-8"})
            urls=parse.urlparse(self.school_data["idsUrl"])
            self.session.headers.update({"Referer":"https://"+urls.netloc+"/wec-counselor-collector-apps/stu/mobile/index.html"})
            json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/queryCollectorProcessingList",json={"pageNumber":1,"pageSize":20}).json()
            self.logger.debug("服务器返回表单数据：%s" %json_resp)
            if json_resp["code"]!="0":
                self.logger.error("获取信息收集报告表单数据出错")
                raise RuntimeError("获取信息收集报告表单数据出错")
            totalSize=json_resp["datas"]["totalSize"]
            pageSize=json_resp["datas"]["pageSize"]
            rows=list()
            t,a=divmod(totalSize,pageSize)
            if a!=0:
                t=t+1
            for pageNumber in range(t):
                json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/queryCollectorProcessingList",json={"pageNumber":pageNumber+1,"pageSize":20}).json()
                self.logger.debug("第 %d 页表单：%s" %(pageNumber+1,json_resp))
                rows=rows+json_resp["datas"]["rows"]
            if len(rows)==0:
                self.logger.error("无未完成的信息收集")
            else:
                for row in rows:
                    self.logger.debug("信息收集信息：%s" %row)
                    self.logger.info("信息收集标题：%s，发布者：%s" %(row["subject"],row["senderUserName"]))
                    collectWid=row["wid"]
                    formWid=row["formWid"]
                    startTime=time.mktime(time.strptime(row["startTime"],"%Y-%m-%d %H:%M"))
                    endTime=time.mktime(time.strptime(row["endTime"],"%Y-%M-%d %H:%M"))
                    currentTime=time.time()
                    if currentTime>endTime:
                        self.logger.error("当前时间已超过问卷回收时间")
                        continue
                    if currentTime<startTime:
                        self.logger.error("当前时间未到问卷开放时间")
                        continue
                    json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/detailCollector",json={"collectWid":collectWid}).json()
                    self.logger.debug("详细收集信息：%s" %json_resp)
                    schoolTaskWid=json_resp['datas']['collector']['schoolTaskWid']
                    json_resp=self.session.post("https://"+urls.netloc+"wec-counselor-collector-apps/stu/collector/getFormFields",json={"pageSize":20,"pageNumber":1,"formWid":formWid,"collectorWid":collectWid}).json()
                    self.logger.debug("获取表单数据：%s" %json_resp)
                    if json_resp["code"]!="0":
                        self.logger.error("获取详细表单数据出错")
                        raise RuntimeError("获取详细表单数据出错")
                    totalSize=json_resp["totalSize"]
                    pageSize=json_resp["pageSize"]
                    rows=list()
                    t,a=divmod(totalSize,pageSize)
                    if a!=0:
                        t=t+1
                    for pageNumber in range(t):
                        json_resp=self.session.post("https://"+urls.netloc+"wec-counselor-collector-apps/stu/collector/getFormFields",json={"pageSize":20,"pageNumber":pageNumber+1,"formWid":formWid,"collectorWid":collectWid}).json()
                        self.logger.debug("第 %d 页详细表单：%s" %(pageNumber+1,json_resp))
                        rows=rows+json_resp["datas"]["rows"]
                    for row in rows:
                        if row["isRequired"]==1:
                            for default in submit_data["defaults"]:
                                if row["title"]==default["title"]:
                                    if row["fieldType"]==2:
                                        # 选择
                                        row["value"]=default["value"]
                                        for fieldItem in row["fieldItems"]:
                                            if fieldItem["content"]!=default["value"]:
                                                row["fieldItems"].remove(fieldItem)
                                    elif row["fieldType"]==1 or row["fieldType"]==5:
                                        # 填空
                                        row["value"]=default["value"]
                                    elif row["fieldType"]==3:
                                        # 多选
                                        for fieldItem in row["fieldItems"]:
                                            del_=True
                                            for default_value in default["value"].split(","):
                                                if fieldItem["content"]==default_value:
                                                    row["value"]=row["value"]+default_value+" "
                                                    del_=False
                                            if del_==True:
                                                row["fieldItems"].remove(fieldItem)
                                    elif row["fieldType"]==4:
                                        # 上传图片
                                        json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/getStsAccess",headers={"Content-Type":"application/json"},json={}).json()
                                        self.logger.debug("上传图片所需认证信息：%s" %json_resp)
                                        fileName=json_resp["datas"]["fileName"]
                                        accessKeyId=json_resp["datas"]["accessKeyId"]
                                        accessSecret=json_resp["datas"]["accessSecret"]
                                        securityToken=json_resp["datas"]["securityToken"]
                                        endPoint=json_resp["datas"]["endPoint"]
                                        bucket=json_resp["datas"]["bucket"]
                                        bucket=oss2.Bucket(auth=oss2.Auth(access_key_id=accessKeyId,access_key_secret=accessSecret),endpoint=endPoint,bucket_name=bucket)
                                        with open(file=default["value"],mode="rb") as reader:
                                            pic=reader.read()
                                        bucket.put_object(key=fileName,data=pic,headers={"x-oss-security-token":securityToken})
                                        bucket.sign_url("PUT",fileName,60)
                                        json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/previewAttachment",json={"ossKey":fileName}).json()
                                        self.logger.debug("服务器返回图片信息：%s" %json_resp)
                                        row["value"]=json_resp["datas"]
                                    else:
                                        self.logger.error("意外的问题类型 %d" %row["fieldType"])
                                        raise RuntimeError("意外的问题类型")
                        else:
                            rows.remove(row)
                    self.session.headers.update(self.submit_header)
                    json_resp=self.session.post("https://"+urls.netloc+"/wec-counselor-collector-apps/stu/collector/submitForm",json={"collectWid":collectWid,"formWid":formWid,"schoolTaskWid":schoolTaskWid,"form":rows}).json()
                    self.logger.debug("提交信息收集回复：%s" %json_resp)
                    if json_resp["message"]=="SUCCESS":
                        msg="%s:今日校园签到提交成功" %time.strftime("%Y-%m-%d %H:%M:%S",time.localtime())
                        self.logger.info("提交信息收集成功")
                        if self.conf["msg"]["qmsg"]!="":
                            self.session.post("https://qmsg.zendee.cn/send/%s" %self.conf["msg"]["qmsg"],params={"msg":msg})
                    else:
                        self.logger.error("提交信息收集失败，原因：%s" %json_resp["message"])
                        raise RuntimeError("提交信息收集失败")
        elif submit_data["enabled"]==False:
            self.logger.info("未启用提交报告，跳过提交报告")
        else:
            self.logger.error("未登录账号")
            raise RuntimeError("未登录账号")
    def start(self):
        start_time=time.time()
        try:
            self.sign()
            self.submit()
        except Exception as e:
            log="处理过程中出现错误，详细内容：%s" %e
            self.logger.error(log)
            if self.conf["msg"]["qmsg"]!="":
                self.session.post("https://qmsg.zendee.cn/send/%s" %self.conf["msg"]["qmsg"],params={"msg":log})
        else:
            mins,secs=divmod(time.time()-start_time,60)
            hours,mins=divmod(mins,60)
            log="处理完成，共计用时 {:0>2d}:{:0>2d}:{:0>2d}".format(int(hours),int(mins),int(secs))
            self.logger.info(log)
            if self.conf["msg"]["qmsg"]!="":
                self.session.post("https://qmsg.zendee.cn/send/%s" %self.conf["msg"]["qmsg"],params={"msg":log})
    def DESEncrypt(self,s):
        iv=base64.b64decode(self.apis["iv"])
        k=des(self.apis["encryptKey"], CBC, iv, pad=None, padmode=PAD_PKCS5)
        encrypted_data=k.encrypt(s)
        return base64.b64encode(encrypted_data).decode()
if __name__=="__main__":
    p=DailyCP()
    p.start()