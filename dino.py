"""dino — 小恐龙跑酷小玩具（Chrome 小恐龙的原创致敬实现）。

玩法：恐龙自动向右跑，跳过仙人掌、低头躲飞鸟，速度越来越快。
纯标准库（argparse/sys/random），无实时键盘输入；
`--auto` 模式下 AI 自动跳跃，适合无头演示与回归测试。

规则：
- 空格/上箭头 = 跳，s/下箭头 = 低头（交互模式）
- 仙人掌必须跳过；飞鸟分高/低两种，低飞的鸟可以低头躲过
- 速度随距离增加而提升；撞到障碍物游戏结束
"""

import argparse
import random
import sys

WIDTH = 40          # 场地宽度（格）
GROUND_Y = 0        # 地面高度（恐龙脚底 y）
JUMP_V = 2.0        # 起跳初速度
GRAVITY = 0.5        # 重力（跳跃顶点约 4~5 格，滞空约 8 帧）
DINO_X = 4          # 恐龙固定横坐标
BASE_SPEED = 1.0    # 初始速度（格/帧）
MAX_SPEED = 3.0     # 速度上限
RAMP_EVERY = 400    # 每跑这么多分提速一档

# 障碍物种类：(名称, 高度, 宽度, y底座, 类型)
OBSTACLES = {
    "cactus_small": {"h": 2, "w": 1, "y": 0, "kind": "cactus"},
    "cactus_tall": {"h": 3, "w": 1, "y": 0, "kind": "cactus"},
    "cactus_wide": {"h": 2, "w": 2, "y": 0, "kind": "cactus"},
    "bird_low": {"h": 1, "w": 2, "y": 0, "kind": "bird"},   # 贴地飞：跳过或低头躲
    "bird_high": {"h": 1, "w": 2, "y": 2, "kind": "bird"},  # 高飞：低头即可躲过
}

DINO_STAND_H = 2
DINO_DUCK_H = 1


class Dino:
    """恐龙状态：y（脚底高度）、vy（竖直速度）、duck（是否低头）。"""

    def __init__(self):
        self.y = 0.0
        self.vy = 0.0
        self.duck = False
        self.airborne = False

    @property
    def height(self):
        return DINO_DUCK_H if self.duck else DINO_STAND_H

    def jump(self):
        if not self.airborne:
            self.vy = JUMP_V
            self.airborne = True
            self.duck = False

    def step(self):
        if self.airborne:
            self.y += self.vy
            self.vy -= GRAVITY
            if self.y <= 0:
                self.y = 0.0
                self.vy = 0.0
                self.airborne = False

    def rect(self):
        """返回 (x0, x1, y0, y1) 碰撞盒。"""
        return (DINO_X, DINO_X + 1, int(round(self.y)), int(round(self.y)) + self.height)


class Obstacle:
    def __init__(self, name, x):
        spec = OBSTACLES[name]
        self.name = name
        self.x = float(x)
        self.w = spec["w"]
        self.h = spec["h"]
        self.y = spec["y"]
        self.kind = spec["kind"]

    def rect(self):
        return (int(self.x), int(self.x) + self.w, self.y, self.y + self.h)


def rects_overlap(a, b):
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class Game:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.dino = Dino()
        self.obstacles = []
        self.score = 0
        self.frames = 0
        self.speed = BASE_SPEED
        self.over = False
        self._dist_since_spawn = 0

    def speed_now(self):
        return min(MAX_SPEED, BASE_SPEED + 0.25 * (self.score // RAMP_EVERY))

    def spawn(self):
        # 随速度提高，障碍物密度略增
        gap = self.rng.randint(18, 34)
        name = self.rng.choice(list(OBSTACLES))
        self.obstacles.append(Obstacle(name, WIDTH + gap))
        self._dist_since_spawn = 0

    def step(self, action=None):
        """action: 'jump' | 'duck' | 'stand' | None。返回 True 表示还活着。"""
        if self.over:
            return False
        if action == "jump":
            self.dino.jump()
        elif action == "duck":
            self.dino.duck = True
        elif action == "stand":
            self.dino.duck = False
        self.dino.step()
        self.speed = self.speed_now()
        for ob in self.obstacles:
            ob.x -= self.speed
        self.obstacles = [ob for ob in self.obstacles if ob.x + ob.w > -2]
        self._dist_since_spawn += self.speed
        if not self.obstacles or self._dist_since_spawn > 24:
            self.spawn()
        self.score += 1
        self.frames += 1
        drect = self.dino.rect()
        for ob in self.obstacles:
            if rects_overlap(drect, ob.rect()):
                self.over = True
                return False
        return True

    def nearest_obstacle(self):
        cands = [ob for ob in self.obstacles if ob.x + ob.w >= DINO_X]
        if not cands:
            return None
        return min(cands, key=lambda ob: ob.x)


def auto_action(game):
    """简单 AI：障碍物接近就跳；高飞鸟则低头。"""
    ob = game.nearest_obstacle()
    if ob is None:
        return "stand"
    dist = ob.x - DINO_X
    if ob.kind == "bird" and ob.y >= 2:
        return "duck" if dist < 10 else "stand"
    # 跳跃需要提前量：滞空约 8 帧，障碍物在 dist/speed 帧后到达，
    # 要求到达时恐龙已升到足够高度（约起跳后 2~6 帧），故提前约 4~5*speed 格起跳
    trigger = 5 * game.speed + 1
    if dist < trigger and not game.dino.airborne:
        return "jump"
    return "stand"


def render(game):
    """文本渲染：两行（空中/地面）+ 地面线。"""
    rows = [[" " for _ in range(WIDTH)] for _ in range(4)]
    d = game.dino
    dy = int(round(d.y))
    dh = d.height
    for yy in range(dh):
        if 0 <= dy + yy < 4:
            rows[3 - (dy + yy)][DINO_X] = "D"
    for ob in game.obstacles:
        ch = "^" if ob.kind == "bird" else "#"
        for dx in range(ob.w):
            for dy2 in range(ob.h):
                x = int(ob.x) + dx
                y = ob.y + dy2
                if 0 <= x < WIDTH and 0 <= y < 4:
                    rows[3 - y][x] = ch
    ground = "-" * WIDTH
    return "\n".join("".join(r) for r in rows) + "\n" + ground


def run_auto(seed=None, frames=1000, verbose=False):
    game = Game(seed)
    # 先预热几个障碍物
    game.spawn()
    jumps = 0
    ducks = 0
    while game.frames < frames and not game.over:
        act = auto_action(game)
        if act == "jump":
            jumps += 1
        elif act == "duck":
            ducks += 1
        game.step(act)
        if verbose and game.frames % 100 == 0:
            print(f"--- 帧 {game.frames} 分数 {game.score} ---")
            print(render(game))
    return game, jumps, ducks


def play_interactive(seed=None):
    print("小恐龙跑酷！输入 j=跳，d=低头，s=站起，q=退出（每行一个命令）")
    game = Game(seed)
    game.spawn()
    print(render(game))
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd == "q":
            break
        act = {"j": "jump", "d": "duck", "s": "stand"}.get(cmd)
        if act is None:
            print("未知命令：j=跳 d=低头 s=站起 q=退出")
            continue
        alive = game.step(act)
        print(render(game))
        print(f"分数 {game.score}  速度 {game.speed:.2f}")
        if not alive:
            print(f"撞上了！最终得分 {game.score}")
            return 1
    print(f"结束，得分 {game.score}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="dino — 终端小恐龙跑酷")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--auto", action="store_true", help="无头自动演示")
    ap.add_argument("--frames", type=int, default=1000, help="自动演示帧数")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.auto:
        game, jumps, ducks = run_auto(args.seed, args.frames, args.verbose)
        status = "撞毁" if game.over else "完成"
        print(f"自动演示{status}：帧数 {game.frames}，得分 {game.score}，"
              f"距离 {game.score}，跳跃 {jumps} 次，低头 {ducks} 次，"
              f"最终速度 {game.speed:.2f}")
        return 0 if not game.over else 1
    if not sys.stdin.isatty():
        print("交互模式需要终端；请用 --auto 做无头演示。", file=sys.stderr)
        return 2
    return play_interactive(args.seed)


if __name__ == "__main__":
    sys.exit(main())
