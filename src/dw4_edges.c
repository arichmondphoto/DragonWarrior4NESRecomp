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
 * The edges are drawn from the map instead:
 *
 *  - Towns, castles, shrines, dungeons: the game keeps the whole map in WRAM
 *    ($7800 cells, W x H = $3F x $40, hero cell $44/$45, border cell $0520;
 *    $7600 the 32 metatiles' four tile numbers, $76C0 their sub-palettes).
 *  - Overworld-style maps ($28 = 0: the main world 256x256, Gottside 64x64,
 *    the Underworld 62x54; hero cell $42/$43): decoded at start from the ROM
 *    (bank $0B, row pointers $A590 / $AB65 / $AE89: 2-byte pointer + two
 *    sizes; bytes are runs, tile = b >> 5, length = (b & 31) + 1, and
 *    b >= $E8 is one tile b - $E0; Data Crystal's DW4 ROM map). Sea (tile 0)
 *    is drawn with one of 16 shoreline metatiles at $7680, picked by which
 *    of its N/E/S/W neighbours (1/2/4/8) are not sea.
 *
 *  - Each frame the nametable is matched against the map around the hero to
 *    find where map cell (0,0) sits in the nametable ring (64 x 30 tiles; it
 *    changes with every map load) and, on the overworld, which world it is.
 *    No match (battles, full-screen menus, the title) = no repair.
 *  - What a map value looks like is learned from the correctly drawn middle
 *    of the screen: the upper bits of a town cell mark rooms and roofs the
 *    game shows or hides, and at a given moment a value is drawn the same way
 *    everywhere (99.6% of the captured map views). Unseen values fall back to
 *    their plain metatile.
 *  - nesrecomp patch 0021's background hook replaces every tile fetched for
 *    the top/bottom 16 lines and left/right 16 pixels by the tile and palette
 *    its map cell should show, and the left 8 pixels are unmasked. Tiles that
 *    are not map tiles (windows, text) are left alone.
 *
 * Widescreen (the runtime menu's "View mode": Native or 16:9, saved in
 * config.ini [Game] ViewMode; headless --view native|16:9): a compositor
 * (cyc_render.h) paints the columns left and right of the 256 from the same
 * map, with the look each map value has on screen this frame, and records
 * every margin tile for the HD presenter (nesrecomp patch 0026) so the pack's
 * art covers the margins too. Screens that are not a map (battles, the title,
 * menus, the casino tables) are pillarboxed. Characters outside the native 256
 * are not drawn.
 *
 * Presentation only: the game's memories are never written. Developer
 * option: --no-edge-repair.
 */
#include "cyc_host_extras.h"
#include "cyc_core.h"
#include "cyc_mod.h"
#include "cyc_render.h"
#include "cyc_video.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EDGE_LINES 16       /* top and bottom lines repaired */
#define EDGE_PIXELS 16      /* left and right pixels repaired */
#define HERO_X 120          /* screen position of the hero's map cell (roughly) */
#define HERO_Y 112
#define CHAR_DX 0           /* a character's top-left sprite relative to its map cell */
#define CHAR_DY (-4)
#define SEA_KEYS 32         /* overworld look keys: tile, or SEA_KEYS + shore mask for sea */

typedef struct { uint8_t q[4], pal; int8_t conf; } Look;
#define LOOKS 4             /* looks remembered per map value (animations, rooms shown/hidden) */
typedef struct { const char *name; uint16_t table; int w, h; uint8_t *cells; } World;

static World worlds[] = {
    { "main", 0xA590, 256, 256, NULL },
    { "Gottside", 0xAB65, 64, 64, NULL },
    { "Underworld", 0xAE89, 62, 54, NULL },
};
#define NWORLDS (int)(sizeof worlds / sizeof worlds[0])

static struct {
    bool enabled, valid, overworld;
    int world;              /* overworld: index into worlds[] */
    int dx, dy;             /* nametable tile of map tile (0,0), mod 64 / 30 */
    int w, h, hx, hy;
    unsigned key;           /* what was learned belongs to this map */
    int search_wait;
    Look look[256][LOOKS];  /* per map value, most seen first after learn() */
    int8_t cur[256];        /* the look each value shows on screen this frame, or -1 */
    int view;               /* 0 native, 1 16:9 */
    int cam_px, cam_py;     /* map pixel at native (0, 0) last presented (compose) */
    unsigned cam_key; bool cam_ok, need_search;
    int step, step_count;   /* the walking step on screen, and frames since it changed */
    uint8_t map_tile[256];  /* tile numbers that belong to the map */
    const uint8_t *ram, *wram, *ciram;
} E = { .enabled = true };

/* ---- the overworlds, decoded from the ROM ---- */

static void decode_worlds(void)
{
    if (worlds[0].cells) return;
    size_t n = cyc_mod_copy_cart_payload(NULL, 0);
    if (n < 12 * 0x4000) return;
    uint8_t *rom = malloc(n);
    if (!rom) return;
    cyc_mod_copy_cart_payload(rom, n);
    const uint8_t *bank = rom + 0x0B * 0x4000;
#define RD(a) bank[(uint16_t)(a) - 0x8000]
    for (int i = 0; i < NWORLDS; i++) {
        World *wd = &worlds[i];
        uint8_t *c = calloc((size_t)wd->w * wd->h, 1);
        if (!c) break;
        for (int y = 0; y < wd->h; y++) {
            uint16_t p = (uint16_t)(wd->table + 4 * y), a = (uint16_t)(RD(p) | RD(p + 1) << 8);
            int size = RD(p + 3), x = 0;
            if (a < 0x8000 || a >= 0xC000) continue;
            for (int k = 0; k < size && x < wd->w && a + k < 0xC000; k++) {
                uint8_t b = RD(a + k);
                if (b >= 0xE8) c[y * wd->w + x++] = (uint8_t)(b - 0xE0);
                else for (int r = (b & 31) + 1; r > 0 && x < wd->w; r--) c[y * wd->w + x++] = (uint8_t)(b >> 5);
            }
        }
        wd->cells = c;
    }
#undef RD
    free(rom);
}

/* ---- nametable ---- */

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

static inline int mod(int a, int m) { a %= m; return a < 0 ? a + m : a; }
static inline int floordiv(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* ---- what a map cell is ---- */

static inline int world_tile(const World *wd, int x, int y) { return wd->cells[mod(y, wd->h) * wd->w + mod(x, wd->w)]; }

/* The look key of map cell (x, y): a town cell's byte, or an overworld tile
 * (sea: SEA_KEYS + which neighbours are not sea). */
static int cell_key(int x, int y)
{
    if (E.overworld) {
        const World *wd = &worlds[E.world];
        int t = world_tile(wd, x, y);
        if (t) return t;
        return SEA_KEYS | (world_tile(wd, x, y - 1) != 0) | (world_tile(wd, x + 1, y) != 0) << 1 |
               (world_tile(wd, x, y + 1) != 0) << 2 | (world_tile(wd, x - 1, y) != 0) << 3;
    }
    if (x < 0 || y < 0 || x >= E.w || y >= E.h) return E.ram[0x520];   /* the map's border cell */
    return E.wram[0x1800 + y * E.w + x];
}

/* The plain metatile of a key (its four tile numbers), or NULL; *pal its palette. */
static const uint8_t *plain(int key, int *pal)
{
    if (E.overworld) {
        if (key >= SEA_KEYS) { *pal = E.wram[0x16C0] & 3; return E.wram + 0x1680 + (key - SEA_KEYS) * 4; }
        *pal = E.wram[0x16C0 + key] & 3; return E.wram + 0x1600 + key * 4;
    }
    if (key >> 5) return NULL;                              /* rooms and roofs: only as learned */
    *pal = E.wram[0x16C0 + key] & 3;
    return E.wram + 0x1600 + key * 4;
}

/* How many cells around the hero the nametable shows as their plain
 * metatile, with map tile (0,0) at nametable tile (dx, dy). */
static int score(int dx, int dy, int *total)
{
    int n = 0, t = 0, pal;
    for (int y = E.hy - 5; y <= E.hy + 5; y++)
        for (int x = E.hx - 6; x <= E.hx + 6; x++) {
            if (!E.overworld && (x < 0 || y < 0 || x >= E.w || y >= E.h)) continue;
            int key = cell_key(x, y);
            /* a room or roof cell (upper bits) shows its base metatile when the
               room is open: it counts when it does (inside buildings every cell is one) */
            bool room = !E.overworld && (key >> 5);
            const uint8_t *d = plain(room ? key & 31 : key, &pal);
            /* only cells that say something: a metatile of four equal tiles
               (blank, flat colour) matches any blank screen */
            if (!d || (d[0] == d[1] && d[1] == d[2] && d[2] == d[3])) continue;
            int tx = 2 * x + dx, ty = mod(2 * y + dy, 30);
            uint8_t a = nt_tile(tx, ty), b = nt_tile(tx + 1, ty), c = nt_tile(tx, ty + 1), e = nt_tile(tx + 1, ty + 1);
            /* a window or text over the cell says nothing about the map */
            if (!E.map_tile[a] || !E.map_tile[b] || !E.map_tile[c] || !E.map_tile[e]) continue;
            bool hit = a == d[0] && b == d[1] && c == d[2] && e == d[3];
            if (room && !hit) continue;
            t++;
            n += hit;
        }
    *total = t;
    return n;
}

/* The best ring offset; true if it explains at least 60% of the cells. */
static bool search(void)
{
    int best = -1, bdx = 0, bdy = 0, total = 0;
    for (int dy = 0; dy < 30; dy += 2)
        for (int dx = 0; dx < 64; dx += 2) {
            int v = score(dx, dy, &total);
            if (v > best) { best = v; bdx = dx; bdy = dy; }
        }
    if (getenv("DW4_EDGES_DEBUG") && getenv("DW4_EDGES_DEBUG")[0] == '2')
        fprintf(stderr, "dw4_edges: search %s best %d of %d at %d,%d hero %d,%d\n",
                E.overworld ? worlds[E.world].name : "town", best, total, bdx, bdy, E.hx, E.hy);
    if (total < 24 || 5 * best < 3 * total) return false;
    E.dx = bdx; E.dy = bdy;
    return true;
}

/* The tile numbers maps are made of: the metatiles (+ shorelines) and what
 * was learned. Anything else on screen is a window or text. */
static void map_tiles(void)
{
    memset(E.map_tile, 0, sizeof E.map_tile);
    for (int i = 0; i < 32 * 4; i++) E.map_tile[E.wram[0x1600 + i]] = 1;
    if (E.overworld) for (int i = 0; i < 16 * 4; i++) E.map_tile[E.wram[0x1680 + i]] = 1;
    for (int i = 0; i < 256; i++)
        for (int j = 0; j < LOOKS; j++)
            if (E.look[i][j].conf > 0)
                for (int k = 0; k < 4; k++) E.map_tile[E.look[i][j].q[k]] = 1;
}

static void locate(bool search, int *fx_, int *fy_, int *tx0_, int *ty0_, int *wx0_, int *wy0_);

static void learn(void)
{
    memset(E.cur, -1, sizeof E.cur);
    /* the middle of the screen, where the game has drawn everything right:
       around the camera when compose found it (scenes look away from the
       hero), else around the hero */
    int mx0 = E.hx - 6, mx1 = E.hx + 6, my0 = E.hy - 5, my1 = E.hy + 5;
    if (E.cam_ok && E.cam_key == E.key && !E.overworld) {
        mx0 = floordiv(E.cam_px + 24, 16); mx1 = floordiv(E.cam_px + 232, 16) - 1;
        my0 = floordiv(E.cam_py + 24, 16); my1 = floordiv(E.cam_py + 216, 16) - 1;
    }
    for (int y = my0; y <= my1; y++)
        for (int x = mx0; x <= mx1; x++) {
            int c = cell_key(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            if (!E.map_tile[q[0]] || !E.map_tile[q[1]] || !E.map_tile[q[2]] || !E.map_tile[q[3]]) continue;  /* a window */
            uint8_t pal = nt_pal(tx, ty);
            Look *l = E.look[c];
            /* a flat cell (four equal tiles) that isn't the value's own metatile:
               a window's blank inside, a dark scene - not a look of the map */
            int pp; const uint8_t *d = plain(E.overworld || !(c >> 5) ? c : c & 31, &pp);
            if (q[0] == q[1] && q[1] == q[2] && q[2] == q[3] && d && memcmp(d, q, 4)) continue;
            /* every look a value shows (animation frames, rooms shown and
               hidden), counted; the least seen one makes room for a new one */
            int j = 0;
            while (j < LOOKS && !(l[j].conf > 0 && !memcmp(l[j].q, q, 4) && l[j].pal == pal)) j++;
            if (j < LOOKS) { if (l[j].conf < 100) l[j].conf++; }
            else {
                j = LOOKS - 1;
                memcpy(l[j].q, q, 4); l[j].pal = pal; l[j].conf = 1;
            }
            while (j > 0 && l[j].conf > l[j - 1].conf) {
                Look t = l[j]; l[j] = l[j - 1]; l[j - 1] = t;
                j--;
            }
        }
    /* the look each value shows most on screen now */
    static uint16_t cnt[256][LOOKS];
    memset(cnt, 0, sizeof cnt);
    for (int y = my0; y <= my1; y++)
        for (int x = mx0; x <= mx1; x++) {
            int c = cell_key(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            for (int j = 0; j < LOOKS; j++)
                if (E.look[c][j].conf > 0 && !memcmp(E.look[c][j].q, q, 4)) { cnt[c][j]++; break; }
        }
    for (int c = 0; c < 256; c++) {
        int b = -1;
        for (int j = 0; j < LOOKS; j++) if (cnt[c][j] && (b < 0 || cnt[c][j] > cnt[c][b])) b = j;
        E.cur[c] = (int8_t)b;
    }
    map_tiles();
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
    bool ow = E.ram[0x28] == 0;
    unsigned key;
    if (ow) {
        if (!worlds[0].cells) goto done;
        E.hx = E.ram[0x42]; E.hy = E.ram[0x43];
        key = 0xFF000000u | (unsigned)E.ram[0x63] << 8 | E.ram[0x64];
    } else {
        E.w = E.ram[0x3F]; E.h = E.ram[0x40]; E.hx = E.ram[0x44]; E.hy = E.ram[0x45];
        if (E.w < 4 || E.h < 4 || E.w * E.h > 0x800) goto done;
        key = (unsigned)E.ram[0x63] << 24 | (unsigned)E.ram[0x64] << 16 | (unsigned)E.w << 8 | (unsigned)E.h;
    }
    if (ow != E.overworld || key != E.key) {
        E.overworld = ow; E.key = key;
        E.cam_ok = false;
        memset(E.look, 0, sizeof E.look); E.search_wait = 0; was = false;
    }
    map_tiles();
    int total, s = was ? score(E.dx, E.dy, &total) : 0;
    if (was && total >= 24 && 2 * s >= total) E.valid = true;
    else if (was && total < 24) E.valid = true;            /* mostly covered by windows: keep what we had */
    else if (E.search_wait > 0 && !was) E.search_wait--;
    else {
        /* (re-based: the overworld moves its ring as the hero walks) */
        if (ow) {
            /* which world: the current one first */
            int first = E.world;
            for (int i = 0; i < NWORLDS && !E.valid; i++) {
                int wi = (first + i) % NWORLDS;
                if (!worlds[wi].cells) continue;
                E.world = wi;
                E.valid = search();
            }
        } else E.valid = search();
        if (E.valid) memset(E.look, 0, sizeof E.look);
        else E.search_wait = 8;
    }
    if (E.valid) {
        /* where the camera looked in the frame just drawn (compose follows it
           frame by frame; searched again when the map was matched anew) */
        if (!was || !E.cam_ok) { E.cam_ok = false; E.need_search = true; }
        learn();
    }
    if (E.valid != was && getenv("DW4_EDGES_DEBUG"))
        fprintf(stderr, "dw4_edges: %s %s offset %d,%d hero %d,%d\n", E.valid ? "on" : "off",
                E.overworld ? worlds[E.world].name : "town/dungeon", E.dx, E.dy, E.hx, E.hy);
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
    if (E.cam_ok && E.cam_key == E.key && !E.overworld) { ex = floordiv(E.cam_px + x, 8); ey = floordiv(E.cam_py + line, 8); }
    wx += 64 * floordiv(ex - wx + 32, 64);
    wy += 30 * floordiv(ey - wy + 15, 30);
    int c = cell_key(floordiv(wx, 2), floordiv(wy, 2)), q = (wx & 1) | (wy & 1) << 1, pal;
    const Look *l = E.look[c];
    /* the game's own drawing of this cell, if it is one of the cell's looks
       (an animation frame, a room's current state): keep it, with that
       look's colours (the attribute byte may not be written yet) */
    int cx = tx & ~1, cy = ty & ~1;
    uint8_t now[4] = { nt_tile(cx, cy), nt_tile(cx + 1, cy), nt_tile(cx, cy + 1), nt_tile(cx + 1, cy + 1) };
    for (int j = 0; j < LOOKS; j++)
        if (l[j].conf > 0 && !memcmp(l[j].q, now, 4)) return l[j].q[q] | l[j].pal << 8;
    const uint8_t *d = plain(c, &pal);
    if (d && !memcmp(d, now, 4)) return d[q] | pal << 8;
    if (l[0].conf > 0) return l[0].q[q] | l[0].pal << 8;   /* the look seen most */
    return d ? d[q] | pal << 8 : -1;
}

/* ---- widescreen ---- */

/* The tile and palette of map tile column wx, row wy (2 per map cell). */
static int map_quarter(int wx, int wy)
{
    int c = cell_key(floordiv(wx, 2), floordiv(wy, 2)), q = (wx & 1) | (wy & 1) << 1, pal;
    const Look *l = E.look[c];
    if (E.cur[c] >= 0 && l[E.cur[c]].conf > 0) return l[E.cur[c]].q[q] | l[E.cur[c]].pal << 8;
    if (l[0].conf > 0) return l[0].q[q] | l[0].pal << 8;
    const uint8_t *d = plain(c, &pal);
    return d ? d[q] | pal << 8 : -1;
}

static void draw_characters(uint32_t *out, int width, int x0, int ox, int oy);
/* Where the camera is: the map tile column/row at native (0, 0) of the frame
 * just drawn (wx0, wy0, and the fine scroll fx, fy), from that frame's scroll
 * and the ring offset. The ring only says it modulo 64 x 30 tiles: the copy
 * is the one near the camera found before, else (search) the one whose map
 * best explains the picture (scenes look away from the hero), else near the
 * hero (the overworld's camera always follows the hero). */
static void locate(bool search, int *fx_, int *fy_, int *tx0_, int *ty0_, int *wx0_, int *wy0_)
{
    int sx = cyc_render_line_scroll_x(120), sy = mod(cyc_render_line_scroll_y(120) - 120, 240);
    int tx0 = sx >> 3, fx = sx & 7, ty0 = sy >> 3, fy = sy & 7;
    int wx0 = mod(tx0 - E.dx, 64), wy0 = mod(ty0 - E.dy, 30);
    bool cam = !search && E.cam_ok && E.cam_key == E.key && !E.overworld;
    int ex = cam ? floordiv(E.cam_px, 8) : 2 * E.hx + floordiv(-HERO_X, 8);
    int ey = cam ? floordiv(E.cam_py, 8) : 2 * E.hy + floordiv(-HERO_Y, 8);
    wx0 += 64 * floordiv(ex - wx0 + 32, 64);
    wy0 += 30 * floordiv(ey - wy0 + 15, 30);
    if (search && !E.overworld) {
        int best = -1, bx = wx0, by = wy0;
        for (int n = -2; n <= 2; n++)
            for (int m = -3; m <= 3; m++) {
                int cx_ = wx0 + 64 * n, cy_ = wy0 + 30 * m, v = 0;
                if (cx_ + 32 < -4 || cx_ > 2 * E.w + 4 || cy_ + 30 < -4 || cy_ > 2 * E.h + 4) continue;
                for (int j = 3; j < 27; j += 2)
                    for (int k = 3; k < 29; k += 2) {
                        int x = cx_ + k, y = cy_ + j;
                        int c = cell_key(floordiv(x, 2), floordiv(y, 2)), q = (x & 1) | (y & 1) << 1, pal;
                        uint8_t g = nt_tile(tx0 + k, mod(ty0 + j, 30));
                        if (!E.map_tile[g]) continue;
                        /* the border's value (all around the map, often inside
                           too) says nothing about which copy this is */
                        if (c == E.ram[0x520]) continue;
                        /* any look of the cell, or its (base) metatile */
                        bool hit = false;
                        for (int L = 0; L < LOOKS && !hit; L++) hit = E.look[c][L].conf > 0 && E.look[c][L].q[q] == g;
                        const uint8_t *d = plain(E.overworld || !(c >> 5) ? c : c & 31, &pal);
                        if (!hit && d) hit = d[q] == g;
                        v += hit ? 2 : -1;
                    }
                v = v * 16 - (abs(n) + abs(m));                   /* ties: nearest the hero */
                if (v > best) { best = v; bx = cx_; by = cy_; }
            }
        if (getenv("DW4_WIDE_DEBUG"))
            fprintf(stderr, "dw4_wide: search %d,%d -> %d,%d (score %d) hero %d,%d off %d,%d\n", wx0, wy0, bx, by, best, E.hx, E.hy, E.dx, E.dy);
        if (best > 0) { wx0 = bx; wy0 = by; }               /* else nothing to go by: near the hero */
    }
    E.cam_px = 8 * wx0 + fx; E.cam_py = 8 * wy0 + fy; E.cam_key = E.key; E.cam_ok = true;
    *fx_ = fx; *fy_ = fy; *tx0_ = tx0; *ty0_ = ty0; *wx0_ = wx0; *wy0_ = wy0;
}

static bool check_wide;

static int compose(uint32_t *out, int width, int height, int x0, const uint32_t *native, void *user)
{
    (void)user; (void)height;
    if (!E.valid) return 0;                                /* not a map: pillarboxed */
    static int ck = -1;
    if (ck < 0) ck = getenv("DW4_WIDE_CHECK") != NULL;
    check_wide = ck;
    static int fl = -1;
    if (fl < 0) fl = getenv("DW4_WIDE_FULL") != NULL;     /* debug: draw the native 256 from the map too */
    bool full = fl;
    int fx, fy, tx0, ty0, wx0, wy0;
    locate(E.need_search, &fx, &fy, &tx0, &ty0, &wx0, &wy0);
    E.need_search = false;
    uint16_t table = cyc_render_line_bg_table(120);
    uint32_t back = cyc_render_color(0);
    for (int i = 0; i < width * 240; i++) out[i] = back;
    int k0 = floordiv(fx - x0, 8) - 1, k1 = floordiv(width - x0 + fx, 8) + 1;
    for (int j = 0; j <= 30; j++) {
        int cy = 8 * j - fy;
        for (int k = k0; k <= k1; k++) {
            int cx = x0 - fx + 8 * k;
            if (cx + 8 <= 0 || cx >= width || (!full && cx >= x0 && cx + 8 <= x0 + 256)) continue;   /* only the margins */
            int t = map_quarter(wx0 + k, wy0 + j);
            if (t < 0) continue;
            uint16_t pattern = (uint16_t)(table + (t & 0xFF) * 16);
            cyc_render_tile(out, width, 240, cx, cy, pattern, t >> 8, 0, NULL, NULL);
            cyc_render_hd_tile(cx, cy, pattern, t >> 8);
        }
    }
    for (int y = 0; y < 240; y++) {
        if (!(cyc_render_line_mask(y) & 0x08))                  /* background off on this line */
            for (int x = 0; x < width; x++) out[y * width + x] = 0xFF000000u;
        if (!full) memcpy(out + y * width + x0, native + y * 256, 256 * sizeof(uint32_t));
    }
    if (check_wide) {
        /* the same formula over the native picture: how often it disagrees
           with what the game drew (map tiles only, not the edge rows) */
        int n = 0, bad = 0;
        for (int j = 2; j < 28; j++)
            for (int k = 2; k < 30; k++) {
                int t = map_quarter(wx0 + k, wy0 + j);
                uint8_t g = nt_tile(tx0 + k, mod(ty0 + j, 30));
                if (t < 0 || !E.map_tile[g]) continue;
                n++; bad += (t & 0xFF) != g;
            }
        fprintf(stderr, "dw4_wide: check %s %d/%d differ\n", E.overworld ? worlds[E.world].name : "town", bad, n);
    }
    /* canvas pixel of map cell (0, 0)'s top-left: map tile column 0 is k = -wx0 */
    draw_characters(out, width, x0, x0 - fx - 8 * wx0 + CHAR_DX, -fy - 8 * wy0 + CHAR_DY);
    return 1;
}

/* ---- characters in the sides ----
 * The map's objects (WRAM $6F60.. 32 entries): cell X $6F60, Y $6F80, the
 * cell they come from $6FA0/$6FC0 (equal when standing), $81 = not on the map;
 * $6FE0 low nibble = the character slot whose frames are at $7200 + slot*64
 * (4 directions x 2 steps x 4 sprites: tile, attribute); $7020 bit 7 = hidden.
 * Everyone walks in step: RAM $3E counts a 16-pixel step down. The game keeps
 * no facing we could find: a walking character faces where it goes, a
 * standing one keeps what it showed on screen last (down if never seen). */
#define OBJS 32
static const uint8_t *frame_sprites(int i, int f) { return E.wram + 0x1200 + 64 * (E.wram[0xFE0 + i] & 15) + f * 8; }

static void draw_characters(uint32_t *out, int width, int x0, int ox, int oy)
{
    static int debug = -1;
    if (debug < 0) debug = getenv("DW4_WIDE_DEBUG") != NULL;
    const uint8_t *oam = cyc_render_oam();
    uint16_t table = cyc_render_line_sprite_table(120);
    int steps[2] = { 0, 0 };
    /* the overworld's characters stand 4 pixels lower in their cells than in towns */
    if (E.overworld) oy += 4;
    for (int i = 0; i < OBJS; i++) {
        const uint8_t *w = E.wram;
        int X = w[0xF60 + i], Y = w[0xF80 + i], PX = w[0xFA0 + i], PY = w[0xFC0 + i];
        if (w[0x1020 + i] & 0x80) continue;                  /* hidden */
        if (E.overworld) {
            if (w[0x1020 + i] & 0x40) continue;              /* left over from the town: the game doesn't draw it here */
            /* world cells (a byte each way): the copy nearest the hero */
            int dx = (int8_t)(uint8_t)(X - E.hx), dy = (int8_t)(uint8_t)(Y - E.hy);
            int pdx = (int8_t)(uint8_t)(PX - X), pdy = (int8_t)(uint8_t)(PY - Y);
            X = E.hx + dx; Y = E.hy + dy;
            /* the previous cell only counts when it is next door (it also holds where the party came out) */
            if (abs(pdx) + abs(pdy) == 1) { PX = X + pdx; PY = Y + pdy; } else { PX = X; PY = Y; }
        } else if (X >= 0x80 || Y >= 0x80) continue;        /* not on the map */
        int rem = (X != PX || Y != PY) ? (E.ram[0x3E] + 1 > 16 ? 16 : E.ram[0x3E] + 1) : 0;
        int face = w[0x1000 + i] & 3;                      /* 0 up 1 right 2 down 3 left */
        /* top-left of the character in canvas pixels (CHAR_DX/DY: where the game puts sprites in a cell) */
        int cx = ox + 16 * X + rem * (PX - X), cy = oy + 16 * Y + rem * (PY - Y);
        /* what the game drew: the frame whose four sprites are in OAM at this place */
        int nx = cx - x0, shown = -1, hits[8];
        for (int f = 0; f < 8; f++) {
            const uint8_t *fs = frame_sprites(i, f);
            int hit = 0;
            for (int k = 0; k < 4; k++)
                for (int s = 0; s < 64; s++) {
                    const uint8_t *o = oam + 4 * s;
                    if (o[0] >= 0xEF || o[1] != fs[2 * k] || (o[2] & 0xC3) != (fs[2 * k + 1] & 0xC3)) continue;
                    int sx = o[3], sy = o[0] + 1;
                    if (abs(sx - (nx + 8 * (k & 1))) <= 2 && abs(sy - (cy + 8 * (k >> 1))) <= 2) { hit++; break; }
                }
            hits[f] = hit;
            if (hit >= 2 && (shown < 0 || hit > hits[shown])) shown = f;
        }
        /* both steps alike (the frames share their sprites): no say on the step */
        bool step_known = shown >= 0 && hits[shown ^ 1] < hits[shown];
        if (debug && nx >= 8 && nx + 16 <= 248 && cy >= 16 && cy + 16 <= 224)
            fprintf(stderr, "dw4_wide: obj %d %s face %d/%d step %d/%d moving %d at %d %d\n", i, shown >= 0 ? "found" : "MISSING",
                    face, shown >= 0 ? shown >> 1 : -1, E.step, shown >= 0 ? shown & 1 : -1, rem != 0, nx, cy);
        if (step_known) steps[shown & 1]++;
        if (cx + 16 <= 0 || cx >= width) continue;
        /* inside the 256: the game's own drawing, except at its side columns,
           where the game leaves out characters that are only partly on screen */
        if (nx >= 0 && nx + 16 <= 256 && (shown >= 0 || (nx >= 16 && nx + 16 <= 240))) continue;
        int f = face * 2 + E.step;
        const uint8_t *fs = frame_sprites(i, f);
        for (int k = 0; k < 4; k++) {
            int sx = cx + 8 * (k & 1), sy = cy + 8 * (k >> 1);
            uint8_t t = fs[2 * k], a = fs[2 * k + 1];
            unsigned fl = (a & 0x40 ? CYC_TILE_HFLIP : 0) | (a & 0x80 ? CYC_TILE_VFLIP : 0);
            /* inside the native picture only where the game drew none of it (cut at the edge) */
            cyc_render_tile(out, width, 240, sx, sy, (uint16_t)(table + t * 16), 4 + (a & 3), fl, NULL, NULL);
            cyc_render_hd_sprite(sx, sy, (uint16_t)(table + t * 16), a & 3, fl);
        }
    }
    /* the walking step: what the characters on screen show, else 16 frames each */
    if (steps[0] || steps[1]) {
        int s = steps[1] > steps[0];
        if (s != E.step) { E.step = s; E.step_count = 0; }
    } else if (++E.step_count >= 16) { E.step ^= 1; E.step_count = 0; }
}

static int get_view_mode(void *ctx) { (void)ctx; return E.view; }

static bool set_view_mode(void *ctx, int mode)
{
    (void)ctx;
    if (mode != 0 && mode != 1) return false;
    E.view = mode;
    cyc_video_set_mode(mode ? NES_VIDEO_16_9 : NES_VIDEO_STOCK);
    return true;
}

static void power_on(void *ctx)
{
    (void)ctx;
    decode_worlds();
    memset(E.look, 0, sizeof E.look);
    E.valid = false; E.key = 0; E.search_wait = 0;
    cyc_ppu_set_bg_tile_hook(E.enabled ? bg_hook : NULL, NULL);
    cyc_ppu_set_show_left(false);
    cyc_render_set_compositor(compose, NULL);
}

static void state_loaded(void *ctx) { power_on(ctx); }

static const CycHostOption options[] = {
    { "--no-edge-repair", false, "draw the map's edge rows as the game left them (as on a TV without overscan)" },
    { "--view", true, "native | 16:9: the picture's width (widescreen draws the map's sides)" },
};

static bool option(void *ctx, const char *name, const char *value)
{
    (void)ctx; (void)value;
    if (!strcmp(name, "--no-edge-repair")) { E.enabled = false; cyc_ppu_set_bg_tile_hook(NULL, NULL); return true; }
    if (!strcmp(name, "--view")) {
        if (!strcmp(value, "native")) return set_view_mode(NULL, 0);
        if (!strcmp(value, "16:9")) return set_view_mode(NULL, 1);
        return false;
    }
    return false;
}

static const CycHostExtras extras = {
    .power_on = power_on,
    .frame_begin = frame_begin,
    .options = options,
    .option_count = sizeof options / sizeof options[0],
    .option = option,
    .state_loaded = state_loaded,
    .view_modes = 1u << 0 | 1u << 1,      /* RECOMP_RUNTIME_UI_VIEW_MODE_NATIVE | _FIXED_16_9 */
    .get_view_mode = get_view_mode,
    .set_view_mode = set_view_mode,
};

const CycHostExtras *cyc_host_extras(void) { return &extras; }
