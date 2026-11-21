// LocSim —— iOS 系统级定位替换（越狱 / rootless）
//
// 原理：所有 App 拿定位都走 CoreLocation.framework 的 CLLocationManager / CLLocation。
// 本 tweak 注入到每个进程（+ 可选注入 SpringBoard），把坐标 getter 改成读配置里的假坐标，
// 并按 10Hz 沿预设路径推进，因此手机端完全离线，不依赖任何电脑。
//
// 配置：/var/mobile/Library/Preferences/com.stv.locsim.plist
//   enabled       BOOL     总开关
//   lat / lng     REAL     当前坐标（会被写回，便于观察）
//   radius        REAL     抖动半径（米，0 = 关闭抖动）
//   biasWeight    REAL     0..1   偏向权重
//   biasBearing   REAL     度，NaN 表示随机
//   route         ARRAY    [{lat,lng,speed}, ...]，有则沿路径走，没有就停在 lat/lng
//   loop          BOOL
// 改完配置发 Darwin 通知 com.stv.locsim.reload 立即生效，或用 SSH：
//   killall -HUP SpringBoard   （粗暴但有效）

#import <CoreLocation/CoreLocation.h>
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import <math.h>

static NSString *const kPrefsPath = @"/var/mobile/Library/Preferences/com.stv.locsim.plist";
static NSString *const kNotify = @"com.stv.locsim.reload";

#pragma mark - 状态

@interface LSState : NSObject
@property (nonatomic, assign) BOOL enabled;
@property (nonatomic, assign) double lat, lng;
@property (nonatomic, assign) double radius, biasWeight, biasBearing;
@property (nonatomic, assign) BOOL loop;
@property (nonatomic, strong) NSArray<NSDictionary *> *route;   // @[{lat,lng,speed}]
@property (nonatomic, assign) NSUInteger seg;                   // 当前段
@property (nonatomic, assign) double travelled;                 // 段内已走米数
@property (nonatomic, assign) double curLat, curLng;
@property (nonatomic, assign) double speed;
@property (nonatomic, assign) NSTimeInterval lastTick;
@property (nonatomic, strong) NSTimer *timer;
+ (instancetype)shared;
- (void)reload;
- (void)start;
@end

static double LSHaversine(double lat1, double lng1, double lat2, double lng2) {
    double R = 6371008.8;
    double p1 = lat1 * M_PI / 180.0, p2 = lat2 * M_PI / 180.0;
    double dp = (lat2 - lat1) * M_PI / 180.0, dl = (lng2 - lng1) * M_PI / 180.0;
    double a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2);
    return 2 * R * atan2(sqrt(a), sqrt(1 - a));
}

static double LSBearing(double lat1, double lng1, double lat2, double lng2) {
    double p1 = lat1 * M_PI / 180.0, p2 = lat2 * M_PI / 180.0;
    double dl = (lng2 - lng1) * M_PI / 180.0;
    double y = sin(dl) * cos(p2);
    double x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl);
    return atan2(y, x) * 180.0 / M_PI;
}

static void LSOffset(double lat, double lng, double east, double north, double *outLat, double *outLng) {
    double mLat = 111132.92 - 559.82 * cos(2 * lat * M_PI / 180.0);
    double mLng = 111132.92 * fmax(0.02, cos(lat * M_PI / 180.0));
    *outLat = lat + north / mLat;
    *outLng = lng + east / mLng;
}

static double LSRandom(double lo, double hi) {
    return lo + (hi - lo) * ((double) arc4random_uniform(1000000) / 1000000.0);
}

static double LSNormal(void) {              // Box-Muller
    double u1 = LSRandom(0.000001, 1.0), u2 = LSRandom(0.0, 1.0);
    return sqrt(-2.0 * log(u1)) * cos(2 * M_PI * u2);
}

@implementation LSState

+ (instancetype)shared {
    static LSState *s;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ s = [LSState new]; [s reload]; [s start]; });
    return s;
}

- (void)reload {
    NSDictionary *d = [NSDictionary dictionaryWithContentsOfFile:kPrefsPath];
    self.enabled = d[@"enabled"] ? [d[@"enabled"] boolValue] : NO;
    self.lat = d[@"lat"] ? [d[@"lat"] doubleValue] : 36.667662;
    self.lng = d[@"lng"] ? [d[@"lng"] doubleValue] : 117.027707;
    self.radius = d[@"radius"] ? [d[@"radius"] doubleValue] : 0.0;
    self.biasWeight = d[@"biasWeight"] ? [d[@"biasWeight"] doubleValue] : 0.0;
    self.biasBearing = d[@"biasBearing"] ? [d[@"biasBearing"] doubleValue] : NAN;
    self.loop = d[@"loop"] ? [d[@"loop"] boolValue] : NO;
    self.route = d[@"route"];
    if (!self.curLat && !self.curLng) {
        self.curLat = self.lat;
        self.curLng = self.lng;
    }
}

- (void)start {
    if (self.timer) return;
    self.lastTick = [NSDate timeIntervalSinceReferenceDate];
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        weakSelf.timer = [NSTimer scheduledTimerWithTimeInterval:0.1 repeats:YES block:^(NSTimer *t) {
            [weakSelf tick];
        }];
    });
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(), NULL,
        (CFNotificationCallback) ^(CFNotificationCenterRef c, void *o, CFStringRef n, const void *u, CFDictionaryRef i) {
            [weakSelf reload];
        }, (__bridge CFStringRef) kNotify, NULL, CFNotificationSuspensionBehaviorDeliverImmediately);
}

- (void)tick {
    NSTimeInterval now = [NSDate timeIntervalSinceReferenceDate];
    double dt = now - self.lastTick;
    self.lastTick = now;
    if (dt <= 0 || dt > 2.0) dt = 0.1;          // 切后台回来别跳点

    if (!self.enabled) return;

    if (self.route.count >= 2) {
        NSDictionary *a = self.route[self.seg];
        NSDictionary *b = self.route[MIN(self.seg + 1, self.route.count - 1)];
        double baseSpeed = a[@"speed"] ? [a[@"speed"] doubleValue] : 1.4;
        if (baseSpeed <= 0) baseSpeed = 1.4;
        double speed = baseSpeed;
        if (self.radius > 0 && self.biasWeight > 0) {
            double f = 1.0 + LSNormal() * 0.15;  // 速度小幅波动，抖动大小的主控交给坐标偏移
            speed = fmax(0.2, fmin(25.0, baseSpeed * f));
        }
        self.speed = speed;
        self.travelled += speed * dt;
        double segLen = LSHaversine([a[@"lat"] doubleValue], [a[@"lng"] doubleValue],
                                    [b[@"lat"] doubleValue], [b[@"lng"] doubleValue]);
        while (self.travelled >= segLen && segLen > 0.01) {
            self.travelled -= segLen;
            self.seg++;
            if (self.seg >= self.route.count - 1) {
                if (self.loop) {
                    self.seg = 0;
                } else {
                    self.seg = self.route.count - 2;
                    self.travelled = segLen;
                    self.speed = 0;
                    break;
                }
            }
            a = self.route[self.seg];
            b = self.route[MIN(self.seg + 1, self.route.count - 1)];
            segLen = LSHaversine([a[@"lat"] doubleValue], [a[@"lng"] doubleValue],
                                 [b[@"lat"] doubleValue], [b[@"lng"] doubleValue]);
        }
        double frac = segLen > 0.01 ? self.travelled / segLen : 0.0;
        self.curLat = [a[@"lat"] doubleValue] + ([b[@"lat"] doubleValue] - [a[@"lat"] doubleValue]) * frac;
        self.curLng = [a[@"lng"] doubleValue] + ([b[@"lng"] doubleValue] - [a[@"lng"] doubleValue]) * frac;
    } else {
        self.curLat = self.lat;
        self.curLng = self.lng;
        self.speed = 0;
    }

    if (self.radius > 0) {
        double bearing = isnan(self.biasBearing) ? LSRandom(0, 360) : self.biasBearing;
        double w = fmax(0.0, fmin(1.0, self.biasWeight));
        double mag = self.radius * (0.35 + 0.65 * ((double) arc4random_uniform(1000) / 1000.0));
        double rad = bearing * M_PI / 180.0;
        double e = sin(rad) * mag, n = cos(rad) * mag;
        double outLat, outLng;
        LSOffset(self.curLat, self.curLng, e * (0.5 + 0.5 * w), n * (0.5 + 0.5 * w), &outLat, &outLng);
        self.curLat = outLat;
        self.curLng = outLng;
    }
}

@end

#pragma mark - Hooks

static CLLocation *LSFakeLocation(void) {
    LSState *s = [LSState shared];
    if (!s.enabled) return nil;
    CLLocationCoordinate2D c = CLLocationCoordinate2DMake(s.curLat, s.curLng);
    CLLocation *loc = [[CLLocation alloc] initWithCoordinate:c
                                                    altitude:55.0
                                          horizontalAccuracy:5.0
                                            verticalAccuracy:5.0
                                                   timestamp:[NSDate date]];
    return loc;
}

%hook CLLocationManager

- (CLLocation *)location {
    CLLocation *f = LSFakeLocation();
    return f ?: %orig;
}

- (void)startUpdatingLocation {
    %orig;
    CLLocation *f = LSFakeLocation();
    if (!f) return;
    // 立刻喂一次，避免等系统回调
    NSArray *sel = @[ @"locationManager:didUpdateLocations:" ];
    id del = self.delegate;
    if ([del respondsToSelector:NSSelectorFromString(sel[0])]) {
        [(id)del locationManager:self didUpdateLocations:@[ f ]];
    }
}

%end

%hook CLLocation

- (CLLocationCoordinate2D)coordinate {
    LSState *s = [LSState shared];
    if (s.enabled) return CLLocationCoordinate2DMake(s.curLat, s.curLng);
    return %orig;
}

- (CLLocationSpeed)speed {
    LSState *s = [LSState shared];
    return s.enabled ? s.speed : %orig;
}

- (CLLocationDirection)course {
    LSState *s = [LSState shared];
    return s.enabled ? 0.0 : %orig;
}

- (CLLocationAccuracy)horizontalAccuracy {
    LSState *s = [LSState shared];
    return s.enabled ? 5.0 : %orig;
}

%end