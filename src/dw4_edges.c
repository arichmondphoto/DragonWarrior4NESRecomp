/*
 * dw4_edges.c - Dragon Warrior IV's map edges at the full 256x240 picture.
 *
 * The NES nametable holds exactly 240 lines, so on a vertically scrolling map
 * the row leaving the screen at one edge is the same memory row the game
 * fills for the other edge. The game writes the incoming row about 10 frames
 * after it starts scrolling into view, and its colours (attribute bytes) 4
 * frames after that: on a TV the overscan hid it, at the full 256x240 it
 * flickers. The left 8 pixels are masked by the game for the same reason.
 *
 * The game keeps the whole map in WRAM ($7800 cells, W x H = $3F x $40;
 * $7600 the 32 metatiles' four tile numbers, $76C0 their sub-palettes), so the
 * edges can be drawn from it:
 *
 *  - Each frame the nametable is matched against the map around the hero
 *    ($44, $45) to find where map cell (0,0) sits in the nametable ring
 *    (64 x 30 tiles; it changes with every map load). No match (battles,
 *    full-screen menus, the title, the overworld) = no repair.
 *  - What a map value looks like is learned from the correctly drawn middle
 *    of the screen: the upper bits of a cell mark rooms and roofs the game
 *    shows or hides, and at a given moment a value is drawn the same way
 *    everywhere (99.6% of the captured map views).
 *  - nesrecomp patch 0021's background hook then replaces every tile fetched
 *    for the top/bottom 16 lines and left/right 16 pixels by the tile and
 *    palette its map cell should show, and the left 8 pixels are unmasked.
 *    Outside the map the game draws its border cell ($0520).
 *    Tiles that are not map tiles (windows, text) are left alone.
 *
 * Presentation only: the game's memories are never written. Developer
 * option: --no-edge-repair.
 */
#include "cyc_host_extras.h"
#include "cyc_core.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define EDGE_LINES 16       /* top and bottom lines repaired */
#define EDGE_PIXELS 16      /* left and right pixels repaired */
#define HERO_X 120          /* screen position of the hero's map cell (roughly) */
#define HERO_Y 112

typedef struct { uint8_t q[4], pal; int8_t conf; } Look;

static struct {
    bool enabled, valid;
    int dx, dy;             /* nametable tile of map tile (0,0), mod 64 / 30 */
    int w, h, hx, hy;
    unsigned key;           /* map id + size: a change resets what was learned */
    int search_wait;
    Look look[256];
    uint8_t map_tile[256];  /* tile numbers that belong to the map */
    const uint8_t *ram, *wram, *ciram;
} E = { .enabled = true };

static inline uint8_t nt_tile(int tx, int ty)
{
    tx &= 63;
    return E.ciram[(tx >> 5) * 0x400 + ty * 32 + (tx & 31)];
}

static inline uint8_t nt_pal(int tx, int ty)
{
    tx &= 63;
    uint8_t a = E.ciram[(tx >> 5) * 0x400 + 0x3C0 + (ty >> 2) * 8 + ((tx & 31) >> 2)];
    return (uint8_t)((a >> (((ty & 2) ? 4 : 0) + ((tx & 2) ? 2 : 0))) & 3);
}

static inline int cell(int x, int y)
{
    if (x < 0 || y < 0 || x >= E.w || y >= E.h) return E.ram[0x520];   /* the map's border cell */
    return E.wram[0x1800 + y * E.w + x];
}

static inline int mod(int a, int m) { a %= m; return a < 0 ? a + m : a; }
static inline int floordiv(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* How many map cells around the hero the nametable shows as their plain
 * metatile, with map tile (0,0) at nametable tile (dx, dy). */
static int score(int dx, int dy, int *total)
{
    int n = 0, t = 0;
    for (int y = E.hy - 5; y <= E.hy + 5; y++)
        for (int x = E.hx - 6; x <= E.hx + 6; x++) {
            if (x < 0 || y < 0 || x >= E.w || y >= E.h) continue;
            int c = cell(x, y);
            const uint8_t *d = E.wram + 0x1600 + (c & 0x1F) * 4;
            int tx = 2 * x + dx, ty = mod(2 * y + dy, 30);
            t++;
            n += nt_tile(tx, ty) == d[0] && nt_tile(tx + 1, ty) == d[1] &&
                 nt_tile(tx, ty + 1) == d[2] && nt_tile(tx + 1, ty + 1) == d[3];
        }
    *total = t;
    return n;
}

static void learn(void)
{
    /* the middle of the screen, where the game has drawn everything right */
    for (int y = E.hy - 5; y <= E.hy + 5; y++)
        for (int x = E.hx - 6; x <= E.hx + 6; x++) {
            int c = cell(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            uint8_t pal = nt_pal(tx, ty);
            Look *l = &E.look[c];
            /* majority vote over cells and frames (Boyer-Moore) */
            if (l->conf > 0 && !memcmp(l->q, q, 4) && l->pal == pal) { if (l->conf < 64) l->conf++; }
            else if (l->conf > 0) l->conf--;
            else { memcpy(l->q, q, 4); l->pal = pal; l->conf = 1; }
        }
    memset(E.map_tile, 0, sizeof E.map_tile);
    for (int i = 0; i < 32 * 4; i++) E.map_tile[E.wram[0x1600 + i]] = 1;
    for (int i = 0; i < 256; i++)
        if (E.look[i].conf > 0)
            for (int k = 0; k < 4; k++) E.map_tile[E.look[i].q[k]] = 1;
}

static void frame_begin(void *ctx)
{
    (void)ctx;
    size_t n;
    E.ram = cyc_cpu_ram();
    E.wram = cyc_cart_ram(&n);
    E.ciram = cyc_ppu_ciram(&n);
    bool was = E.valid;
    E.valid = false;
    if (!E.enabled || !E.ram || !E.wram || !E.ciram || n < 0x800) goto done;
    if (E.ram[0x28] == 0) goto done;                       /* overworld-style maps: not yet */
    E.w = E.ram[0x3F]; E.h = E.ram[0x40]; E.hx = E.ram[0x44]; E.hy = E.ram[0x45];
    if (E.w < 4 || E.h < 4 || E.w * E.h > 0x800) goto done;
    unsigned key = (unsigned)E.ram[0x63] << 24 | (unsigned)E.ram[0x64] << 16 | (unsigned)E.w << 8 | (unsigned)E.h;
    if (key != E.key) { E.key = key; memset(E.look, 0, sizeof E.look); E.search_wait = 0; was = false; }
    int total, s = was ? score(E.dx, E.dy, &total) : 0;
    if (was && total && 2 * s >= total) E.valid = true;
    else if (E.search_wait > 0) E.search_wait--;
    else {
        int best = -1, bdx = 0, bdy = 0;
        for (int dy = 0; dy < 30; dy += 2)
            for (int dx = 0; dx < 64; dx += 2) {
                int v = score(dx, dy, &total);
                if (v > best) { best = v; bdx = dx; bdy = dy; }
            }
        if (total && 5 * best >= 3 * total) { E.dx = bdx; E.dy = bdy; E.valid = true; memset(E.look, 0, sizeof E.look); }
        else E.search_wait = 8;
    }
    if (E.valid) learn();
done:
    cyc_ppu_set_show_left(E.valid);
}

static int bg_hook(void *ctx, int line, int x, uint16_t v, uint8_t tile)
{
    (void)ctx;
    if (!E.valid) return -1;
    if (line >= EDGE_LINES && line < 240 - EDGE_LINES && x >= EDGE_PIXELS && x < 256 - EDGE_PIXELS) return -1;
    if (!E.map_tile[tile]) return -1;                       /* a window or text */
    int tx = (v & 31) + ((v >> 10) & 1) * 32, ty = (v >> 5) & 31;
    if (ty >= 30) return -1;
    /* the map tile column/row this nametable tile stands for, nearest to the hero */
    int wx = mod(tx - E.dx, 64), wy = mod(ty - E.dy, 30);
    int ex = 2 * E.hx + floordiv(x - HERO_X, 8), ey = 2 * E.hy + floordiv(line - HERO_Y, 8);
    wx += 64 * floordiv(ex - wx + 32, 64);
    wy += 30 * floordiv(ey - wy + 15, 30);
    int c = cell(floordiv(wx, 2), floordiv(wy, 2)), q = (wx & 1) | (wy & 1) << 1;
    const Look *l = &E.look[c];
    if (l->conf > 0) return l->q[q] | l->pal << 8;
    if (!(c >> 5)) {
        int mt = c & 0x1F;
        return E.wram[0x1600 + mt * 4 + q] | (E.wram[0x16C0 + mt] & 3) << 8;
    }
    return -1;
}

static void power_on(void *ctx)
{
    (void)ctx;
    memset(E.look, 0, sizeof E.look);
    E.valid = false; E.key = 0; E.search_wait = 0;
    cyc_ppu_set_bg_tile_hook(E.enabled ? bg_hook : NULL, NULL);
    cyc_ppu_set_show_left(false);
}

static void state_loaded(void *ctx) { power_on(ctx); }

static const CycHostOption options[] = {
    { "--no-edge-repair", false, "draw the map's edge rows as the game left them (as on a TV without overscan)" },
};

static bool option(void *ctx, const char *name, const char *value)
{
    (void)ctx; (void)value;
    if (!strcmp(name, "--no-edge-repair")) { E.enabled = false; cyc_ppu_set_bg_tile_hook(NULL, NULL); return true; }
    return false;
}

static const CycHostExtras extras = {
    .power_on = power_on,
    .frame_begin = frame_begin,
    .options = options,
    .option_count = sizeof options / sizeof options[0],
    .option = option,
    .state_loaded = state_loaded,
};

const CycHostExtras *cyc_host_extras(void) { return &extras; }
