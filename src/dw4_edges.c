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
#include <math.h>
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
    unsigned cam_key; bool cam_ok, need_search, cam_hero;
    int room46;                    /* the room ($46) the picture on screen was drawn for */
    int room_alt, alt_frames, alt, screen_miss;      /* the other room while the game redraws the screen for a new one */
    int row_tag[32]; int8_t row_alt[32];
    int recheck;            /* frames since the town offset was last checked against the others */
    int valid_frames;       /* frames the map has been matched in a row */
    /* towns: how each room (cell key >> 5; 0 = not in a room) shows now, from
       its cells on screen: open (its metatiles) or hidden (black, a roof:
       that look). Cells never seen take their room's state */
    struct { uint8_t state, q[4], pal; } room[8];
    int room_last;          /* the room (1-7) whose state was seen last */
    /* towns: the border around the map is drawn in a pattern (forests of two
       kinds, a tree's trunk), so its looks are kept by position (x, y mod 16) */
    struct { uint8_t q[4], pal, ok; } border[16][16];
    int bpx, bpy;           /* the border pattern's period (smallest consistent with what was seen) */
    bool border_new;        /* the border table changed since the period was worked out */
    /* towns: each cell as it looked when last on screen, with its room's state
       then (some maps draw cells of one value differently by place) */
    struct { uint8_t q[4], pal, st; } cellmem[128 * 128];
    uint8_t multi[256];     /* values showing more than one look on screen now */
    uint8_t ram3e;          /* the hero's step counter at the start of the frame */
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

#define WIN(g) ((g) >= 1 && (g) <= 0x8B)                 /* text and window frames */
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
    /* outside the map ($D3E6 -> $D459): the border cell $0520, or with
       $0550 bit 7 a pattern of it and $058C, 8 cells each way */
    if (x < 0 || y < 0 || x >= E.w || y >= E.h) {
        static const uint8_t rows[8] = { 0x44, 0xEE, 0xEE, 0x44, 0x11, 0xBB, 0xBB, 0x11 };
        if ((E.ram[0x550] & 0x80) && !((1 << (x & 7)) & rows[y & 7])) return E.ram[0x58C];
        return E.ram[0x520];
    }
    return E.wram[0x1800 + y * E.w + x];
}

/* The metatile a town/dungeon cell value is drawn with, the hero in room
 * `room` ($46: the value's upper three bits). The game's own rule ($D4F3):
 * a cell of the hero's room shows its metatile (the low five bits); any other
 * shows metatile $20 from outside (a roof) or $21 from inside a room (the
 * dark), but on maps of type 4 ($07BA) the border's value shows everywhere. */
static int town_meta(int v, int room)
{
    if ((v & 0xE0) == room) return v & 0x1F;
    if (E.ram[0x7BA] == 4 && (v & 0x1F) == E.ram[0x520]) return v & 0x1F;
    return room ? 0x21 : 0x20;
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
            bool room = false;
            const uint8_t *d = E.overworld ? plain(key, &pal) : E.wram + 0x1600 + 4 * town_meta(key, E.room46);
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

/* How many map tiles on screen are not what the map shows for room E.room46
 * (the screen as the camera has it; around the hero before it is found). */
static int room_miss(void)
{
    int miss = 0;
    bool cam = E.cam_ok && E.cam_key == E.key;
    int wx0 = cam ? floordiv(E.cam_px, 8) : 2 * E.hx - 14, wy0 = cam ? floordiv(E.cam_py, 8) : 2 * E.hy - 12;
    for (int j = 2; j < 28; j += 2)
        for (int k = 2; k < 30; k += 2) {
            int wx = wx0 + k, wy = wy0 + j, m = town_meta(cell_key(floordiv(wx, 2), floordiv(wy, 2)), E.room46);
            uint8_t g = nt_tile(wx + E.dx, mod(wy + E.dy, 30));
            if (E.map_tile[g]) miss += g != E.wram[0x1600 + 4 * m + ((wx & 1) | (wy & 1) << 1)];
        }
    return miss;
}

/* The best ring offset; true if it explains at least 60% of the cells. */
static bool search(void)
{
    int best = -1, bdx = 0, bdy = 0, total = 0, t;
    for (int dy = 0; dy < 30; dy += 2)
        for (int dx = 0; dx < 64; dx += 2) {
            int v = score(dx, dy, &t);
            if (v > best) { best = v; bdx = dx; bdy = dy; total = t; }   /* (the best one's total) */
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
    for (int i = 0; i < (E.overworld ? 32 : 34) * 4; i++) E.map_tile[E.wram[0x1600 + i]] = 1;
    if (E.overworld) for (int i = 0; i < 16 * 4; i++) E.map_tile[E.wram[0x1680 + i]] = 1;
    for (int i = 0; i < 256; i++)
        for (int j = 0; j < LOOKS; j++)
            if (E.look[i][j].conf > 0)
                for (int k = 0; k < 4; k++) E.map_tile[E.look[i][j].q[k]] = 1;
    /* tiles $01-$8B are text and window frames, never in a map's metatiles
       (all town, dungeon and world metatile sets checked) */
    for (int i = 1; i <= 0x8B; i++) E.map_tile[i] = 0;
}

static void locate(bool search, int *fx_, int *fy_, int *tx0_, int *ty0_, int *wx0_, int *wy0_);

static uint8_t objsnap[0x1600];   /* WRAM object table + frames, at the start of the frame */

/* Whether nametable tile (tx, ty), of flat tile f, is the blank inside of a
 * window: along its row, the first other tile on each side is not a map tile. */
static bool in_window(int tx, int ty, uint8_t f)
{
    int side = 0;
    for (int dir = -1; dir <= 1; dir += 2)
        for (int i = 1; i < 32; i++) {
            uint8_t g = nt_tile(tx + dir * i, ty);
            if (g == f) continue;
            side += !E.map_tile[g];
            break;
        }
    return side == 2;
}

static int dbg_frame;
static void locate(bool search, int *fx_, int *fy_, int *tx0_, int *ty0_, int *wx0_, int *wy0_);
static void learn(void)
{
    memset(E.cur, -1, sizeof E.cur);
    /* the middle of the screen, where the game has drawn everything right:
       around the camera when compose found it (scenes look away from the
       hero), else around the hero */
    int mx0 = E.hx - 7, mx1 = E.hx + 7, my0 = E.hy - 6, my1 = E.hy + 6;
    if (E.cam_ok && E.cam_key == E.key && !E.overworld) {
        /* the whole picture but its outer 8 pixels (a scrolling edge being drawn) and the bottom rows */
        mx0 = floordiv(E.cam_px + 8 + 15, 16); mx1 = floordiv(E.cam_px + 248, 16) - 1;
        my0 = floordiv(E.cam_py + 8 + 15, 16); my1 = floordiv(E.cam_py + 224, 16) - 1;
    }
    /* a screen still being drawn (entering a map: cleared, then filled in) is
       mostly flat: its blank cells are not looks in the first frames then */
    int flats = 0, cells = 0;
    for (int y = my0; y <= my1; y++)
        for (int x = mx0; x <= mx1; x++) {
            int tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t a = nt_tile(tx, ty);
            cells++;
            flats += a == nt_tile(tx + 1, ty) && a == nt_tile(tx, ty + 1) && a == nt_tile(tx + 1, ty + 1);
        }
    bool flat_ok = E.valid_frames >= 30 || flats * 2 < cells;
    for (int y = my0; y <= my1; y++)
        for (int x = mx0; x <= mx1; x++) {
            int c = cell_key(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            /* a window or text (tiles $01-$8B; not "a tile no metatile has":
               a roof's tile is in none, and roofs were never learned) */
            if (WIN(q[0]) || WIN(q[1]) || WIN(q[2]) || WIN(q[3])) continue;
            uint8_t pal = nt_pal(tx, ty);
            if (!flat_ok && q[0] == q[1] && q[1] == q[2] && q[2] == q[3]) {
                int pp2; const uint8_t *d2 = plain(E.overworld || !(c >> 5) ? c : c & 31, &pp2);
                if (!d2 || memcmp(d2, q, 4)) continue;
            }
            Look *l = E.look[c];
            /* a flat cell (four equal tiles) that isn't the value's own metatile
               inside a window (its blank inside: window tiles further along the
               row on both sides) is not a look of the map; elsewhere it is (rooms
               and the outside go black depending on where the hero is) */
            int pp; const uint8_t *d = plain(E.overworld || !(c >> 5) ? c : c & 31, &pp);
            if (q[0] == q[1] && q[1] == q[2] && q[2] == q[3] && d && memcmp(d, q, 4) && in_window(tx, ty, q[0])) continue;
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
    int open_n[8] = { 0 }, hid_n[8] = { 0 };
    static int16_t cellxy[512][2]; int ncell = 0;
    for (int y = my0; y <= my1; y++)
        for (int x = mx0; x <= mx1; x++) {
            int c = cell_key(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            for (int j = 0; j < LOOKS; j++)
                if (E.look[c][j].conf > 0 && !memcmp(E.look[c][j].q, q, 4)) { cnt[c][j]++; break; }
            if (E.overworld) continue;
            if (WIN(q[0]) || WIN(q[1]) || WIN(q[2]) || WIN(q[3])) continue;
            if (q[0] == q[1] && q[1] == q[2] && q[2] == q[3] && in_window(tx, ty, q[0])) continue;
            if (x < 0 || y < 0 || x >= E.w || y >= E.h) {
                /* (only with the camera found and the hero in its picture, a
                   few frames on: a map just matched may still be half drawn
                   at another offset, and what the border shows is kept) */
                if (!(E.cam_ok && E.cam_key == E.key && E.cam_hero && E.valid_frames >= 8)) continue;
                if (E.valid_frames >= 30 || !(q[0] == q[1] && q[1] == q[2] && q[2] == q[3])) {
                    __typeof__(E.border[0][0]) *b = &E.border[x & 15][y & 15];
                    uint8_t bp = nt_pal(tx, ty);
                    if (!b->ok || memcmp(b->q, q, 4) || b->pal != bp) {
                        E.border_new = true;
                        if (getenv("DW4_BORDER_LOG"))
                            fprintf(stderr, "f%d border set %d,%d = %02X%02X%02X%02X/%d (was %d) dx %d dy %d cam %d,%d ok %d hero %d,%d vf %d s3e %d wh %d,%d key %08X\n",
                                    dbg_frame, x, y, q[0], q[1], q[2], q[3], bp, b->ok, E.dx, E.dy, E.cam_px, E.cam_py, E.cam_ok, E.hx, E.hy, E.valid_frames, E.ram[0x3E], E.w, E.h, E.key);
                    }
                    memcpy(b->q, q, 4); b->pal = bp; b->ok = 1;
                }
                continue;
            }
            int r = c >> 5, pp; const uint8_t *d = plain(c & 31, &pp);
            if (E.w <= 128 && E.h <= 128 && (E.valid_frames >= 30 || !(q[0] == q[1] && q[1] == q[2] && q[2] == q[3]))) {
                __typeof__(E.cellmem[0]) *m = &E.cellmem[y * 128 + x];
                memcpy(m->q, q, 4); m->pal = nt_pal(tx, ty);
                m->st = (uint8_t)(d && !memcmp(d, q, 4) ? 1 : 2) | 4;    /* open/hidden then; 4 = known */
                cellxy[ncell][0] = (int16_t)x; cellxy[ncell][1] = (int16_t)y; if (ncell < 511) ncell++;
            }
            if (!d) continue;
            if (!memcmp(d, q, 4)) open_n[r]++;
            else {
                hid_n[r]++;
                memcpy(E.room[r].q, q, 4); E.room[r].pal = nt_pal(tx, ty);
            }
        }
    for (int r = 0; r < 8; r++)
        if (open_n[r] + hid_n[r] >= 2) {
            E.room[r].state = hid_n[r] > open_n[r] ? 2 : 1;
            if (r) E.room_last = r;
        }
    for (int c = 0; c < 256; c++) {
        int b = -1, kinds = 0;
        for (int j = 0; j < LOOKS; j++) if (cnt[c][j]) { kinds++; if (b < 0 || cnt[c][j] > cnt[c][b]) b = j; }
        E.cur[c] = (int8_t)b;
        E.multi[c] = kinds > 1;
    }
    if (!E.overworld && E.border_new) {
        E.border_new = false;
        static const int per[5] = { 1, 2, 4, 8, 16 };
        E.bpx = E.bpy = 16;
        int bestn = 16 * 16 + 1;
        for (int a = 0; a < 5; a++)
            for (int b = 0; b < 5; b++) {
                int px = per[a], py = per[b];
                if (px * py >= bestn) continue;
                bool ok = true;
                for (int i = 0; i < 256 && ok; i++) {
                    int x = i & 15, y = i >> 4;
                    if (!E.border[x][y].ok) continue;
                    int rx = x % px, ry = y % py;
                    for (int j = 0; j < 256 && ok; j++) {
                        int x2 = j & 15, y2 = j >> 4;
                        if (j <= i || !E.border[x2][y2].ok || x2 % px != rx || y2 % py != ry) continue;
                        ok = !memcmp(E.border[x][y].q, E.border[x2][y2].q, 4) && E.border[x][y].pal == E.border[x2][y2].pal;
                    }
                }
                if (ok) { bestn = px * py; E.bpx = px; E.bpy = py; }
            }
    }
    (void)cellxy;
    map_tiles();
}

static void frame_begin(void *ctx)
{
    (void)ctx;
    size_t n;
    E.ram = cyc_cpu_ram(); dbg_frame++;
    E.wram = cyc_cart_ram(&n);
    /* the characters as the frame about to be drawn shows them: the game
       builds its sprites from the object table one frame behind */
    if (E.wram && n >= 0x1600) memcpy(objsnap + 0xF60, E.wram + 0xF60, 0x1600 - 0xF60);
    if (E.ram) E.ram3e = E.ram[0x3E];
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
        /* entering a map, the hero's cell is still the old map's for a few
           frames (and the screen still the old picture) */
        if (E.hx >= E.w || E.hy >= E.h) goto done;
        key = (unsigned)E.ram[0x63] << 24 | (unsigned)E.ram[0x64] << 16 | (unsigned)E.w << 8 | (unsigned)E.h;
    }
    if (ow != E.overworld || key != E.key) {
        E.overworld = ow; E.key = key;
        E.cam_ok = false; E.room46 = E.room_alt = E.ram[0x46] & 0xE0; E.alt_frames = 0;
        memset(E.look, 0, sizeof E.look); memset(E.room, 0, sizeof E.room); E.room_last = 0; memset(E.border, 0, sizeof E.border); memset(E.cellmem, 0, sizeof E.cellmem); E.search_wait = 0; was = false;
    }
    map_tiles();
    /* The room the picture was drawn for: the hero's ($46), but the game
       redraws the screen a little after it changes, and a scene can show
       another: when the picture disagrees, the room that explains it best. */
    if (!ow) {
        int want = E.ram[0x46] & 0xE0, old = E.room46;
        for (int i = 0; i < 32; i++) E.row_tag[i] = 0x7FFFFFFF;
        E.screen_miss = 0;
        if (!was) E.room46 = E.room_alt = want;
        else {
            E.room_alt = E.room46;                          /* (whole-screen: no rows of another room) */
            int m0 = room_miss();
            if (m0 || E.room46 != want) {
                int best = m0, br = E.room46;
                for (int i = 0; i < 9; i++) {
                    E.room46 = i == 0 ? want : (i - 1) << 5;
                    int v = room_miss();
                    if (v < best || (v == best && i == 0)) { best = v; br = E.room46; }
                }
                E.room46 = br;
            }
            E.screen_miss = room_miss();
            if (E.room46 != old) { E.alt = old; E.alt_frames = 90; }
            else if (E.alt_frames > 0) E.alt_frames--;
            E.room_alt = E.alt_frames > 0 ? E.alt : E.room46;
        }
    }
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
        } else {
            E.valid = search();
            if (!E.valid && E.ram[0x3E] == 0) {
                /* nothing on screen to match (a plain floor or field, a dark
                   room): with the hero standing still, its cell is drawn at
                   screen tile (16, 14) - take the ring offset from the scroll.
                   compose still checks the picture agrees every frame */
                int sx = cyc_render_line_scroll_x(120), sy = mod(cyc_render_line_scroll_y(120) - 120, 240);
                if (getenv("DW4_EDGES_DEBUG")) fprintf(stderr, "dw4_edges: hero offset try scroll %d,%d\n", sx, sy);
                if (!(sx & 7) && !(sy & 7)) {
                    int t2, s2;
                    int dx = mod((sx >> 3) + 16 - 2 * E.hx, 64), dy = mod((sy >> 3) + 14 - 2 * E.hy, 30);
                    s2 = score(dx, dy, &t2);
                    if (2 * s2 >= t2) { E.dx = dx; E.dy = dy; E.valid = true; }
                }
            }
        }
        if (E.valid) { memset(E.look, 0, sizeof E.look); memset(E.room, 0, sizeof E.room); E.room_last = 0; memset(E.border, 0, sizeof E.border); memset(E.cellmem, 0, sizeof E.cellmem); }
        else E.search_wait = 8;
    }
    if (E.valid && was && !ow && ++E.recheck >= 8) {
        /* towns: room cells only count where they show, so a wrong offset
           matched early (the screen half drawn) can go on looking right;
           every 8 frames, another offset that explains clearly more wins */
        E.recheck = 0;
        int t, cur = score(E.dx, E.dy, &t), best = cur, bdx = E.dx, bdy = E.dy;
        for (int dy = 0; dy < 30; dy += 2)
            for (int dx = 0; dx < 64; dx += 2) {
                int v = score(dx, dy, &t);
                if (v > best) { best = v; bdx = dx; bdy = dy; }
            }
        if (best >= cur + cur / 4 + 4 && (bdx != E.dx || bdy != E.dy)) {
            if (getenv("DW4_EDGES_DEBUG"))
                fprintf(stderr, "dw4_edges: recheck %d,%d (%d) -> %d,%d (%d) hero %d,%d\n", E.dx, E.dy, cur, bdx, bdy, best, E.hx, E.hy);
            E.dx = bdx; E.dy = bdy;
            memset(E.look, 0, sizeof E.look); memset(E.room, 0, sizeof E.room); E.room_last = 0; memset(E.border, 0, sizeof E.border); memset(E.cellmem, 0, sizeof E.cellmem); was = false;
        }
    }
    if (E.valid) {
        /* where the camera looked in the frame just drawn (compose follows it
           frame by frame; searched again when the map was matched anew) */
        if (!was || !E.cam_ok) { E.cam_ok = false; E.need_search = true; }
        E.valid_frames = was ? E.valid_frames + 1 : 0;
        /* towns: follow the camera to the frame just drawn before learning
           from it (compose may not run every frame: the window hidden, fast
           forward, a slower display; a camera left behind puts the learning
           window over cells off screen, whose nametable rows and columns hold
           other cells, and those were learned as the border's looks) */
        if (!E.overworld) {
            int a, b, c, d, e, f;
            locate(E.need_search, &a, &b, &c, &d, &e, &f);
            E.need_search = false;
        }
        if (E.overworld) learn();                           /* (towns and dungeons need none: town_meta) */
    } else E.valid_frames = 0;
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

/* The room map row y is drawn for on screen: the game redraws the screen row
 * by row over a few frames when the hero changes room, so each row is asked. */
static int row_bad(int y, int room)
{
    int bad = 0, x0 = floordiv(E.cam_px, 16) + 1;
    for (int x = x0; x < x0 + 14; x++) {
        int m = town_meta(cell_key(x, y), room);
        for (int q = 0; q < 4; q++) {
            uint8_t g = nt_tile(2 * x + E.dx + (q & 1), mod(2 * y + E.dy + (q >> 1), 30));
            if (E.map_tile[g]) bad += E.wram[0x1600 + 4 * m + q] != g;
        }
    }
    return bad;
}

static int row_room(int y)
{
    if (!E.screen_miss || !E.cam_ok || E.cam_key != E.key) return E.room46;
    int i = y & 31;
    if (E.row_tag[i] != y) {
        int best = row_bad(y, E.room46), br = E.room46;
        /* (a row on screen only: rows off it take the screen's room) */
        if (best && y >= floordiv(E.cam_py, 16) && y <= floordiv(E.cam_py + 239, 16))
            if (E.room_alt != E.room46 && row_bad(y, E.room_alt) < best) br = E.room_alt;
        E.row_tag[i] = y; E.row_alt[i] = (int8_t)(br >> 5);
    }
    return E.row_alt[i] << 5;
}

/* The tile and palette of map tile column wx, row wy (2 per map cell). */
static int map_quarter(int wx, int wy)
{
    int x = floordiv(wx, 2), y = floordiv(wy, 2);
    int c = cell_key(x, y), q = (wx & 1) | (wy & 1) << 1, pal;
    if (!E.overworld) {                                     /* towns and dungeons: as the game draws it */
        int m = town_meta(c, row_room(y));
        return E.wram[0x1600 + 4 * m + q] | (E.wram[0x16C0 + m] & 3) << 8;
    }
    if (!E.overworld && (x < 0 || y < 0 || x >= E.w || y >= E.h)) {
        if (E.border[x & 15][y & 15].ok) return E.border[x & 15][y & 15].q[q] | E.border[x & 15][y & 15].pal << 8;
        /* a place never seen: the pattern's same place seen elsewhere */
        int px = E.bpx ? E.bpx : 16, py = E.bpy ? E.bpy : 16;
        for (int by = (y & 15) % py; by < 16; by += py)
            for (int bx = (x & 15) % px; bx < 16; bx += px)
                if (E.border[bx][by].ok) return E.border[bx][by].q[q] | E.border[bx][by].pal << 8;
    }
    const Look *l = E.look[c];
    /* the cell as last seen: where its value shows several looks on screen
       now (looks by place), or its room still shows as it did then */
    const __typeof__(E.cellmem[0]) *m = NULL;
    if (!E.overworld && x >= 0 && y >= 0 && x < E.w && y < E.h && x < 128 && y < 128 && (E.cellmem[y * 128 + x].st & 4))
        m = &E.cellmem[y * 128 + x];
    if (m && E.cur[c] >= 0 && E.multi[c]) return m->q[q] | m->pal << 8;
    if (E.cur[c] >= 0 && l[E.cur[c]].conf > 0) return l[E.cur[c]].q[q] | l[E.cur[c]].pal << 8;
    if (m && (E.room[c >> 5].state == 0 || E.room[c >> 5].state == (m->st & 3))) return m->q[q] | m->pal << 8;
    if (!E.overworld) {
        /* not on screen now: as its room shows */
        int r = c >> 5, st = E.room[r].state;
        if (r && r == cell_key(E.hx, E.hy) >> 5) st = 1;   /* the hero's room is open */
        if (!st && r) {
            /* a room not seen yet: hidden, like the room seen last (its roof)
               or black (caves are dark until a room is entered) */
            int h = E.room_last && E.room[E.room_last].state == 2 ? E.room_last : 0;
            for (int i = 7; i > 0 && !h; i--) if (E.room[i].state == 2) h = i;   /* (a building of several rooms: one roof) */
            if (!h) return -1;
            r = h; st = 2;
        }
        if (st == 2) return E.room[r].q[q] | E.room[r].pal << 8;
        if (st == 1) {
            const uint8_t *d = plain(c & 31, &pal);
            if (d) return d[q] | pal << 8;
        }
    }
    if (l[0].conf > 0) return l[0].q[q] | l[0].pal << 8;   /* the look seen most */
    const uint8_t *d = plain(E.overworld ? c : c & 31, &pal);
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
    int hx = 2 * E.hx + floordiv(-HERO_X, 8), hy = 2 * E.hy + floordiv(-HERO_Y, 8);
    int ex = cam ? floordiv(E.cam_px, 8) : hx;
    int ey = cam ? floordiv(E.cam_py, 8) : hy;
    int cwx = wx0 + 64 * floordiv(hx - wx0 + 32, 64), cwy = wy0 + 30 * floordiv(hy - wy0 + 15, 30);
    wx0 += 64 * floordiv(ex - wx0 + 32, 64);
    wy0 += 30 * floordiv(ey - wy0 + 15, 30);
    /* following the camera, it has gone to another copy of the ring than the
       one near the hero: one of them is wrong - ask the picture */
    if (cam && (cwx != wx0 || cwy != wy0)) {
        if (getenv("DW4_EDGES_DEBUG")) fprintf(stderr, "dw4_wide: camera %d,%d vs hero %d,%d: search\n", wx0, wy0, cwx, cwy);
        search = true;
    }
    if (search && !E.overworld) {
        int best = -1, bx = wx0, by = wy0;
        /* the copy that has the hero on screen (one at most; none in a scene
           that looks away), and what the picture says for it */
        int hero_v = 0, hbx = 0, hby = 0; bool hero_copy = false;
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
                if (2 * E.hx >= cx_ && 2 * E.hx < cx_ + 32 && 2 * E.hy >= cy_ && 2 * E.hy < cy_ + 30) {
                    hero_copy = true; hero_v = v; hbx = cx_; hby = cy_;
                }
                if (v > best) { best = v; bx = cx_; by = cy_; }
            }
        /* The hero is on screen but for a few scenes, so its copy is the one:
           another needs the picture to say so clearly (a screen half drawn,
           or mostly windows, matched a copy a ring away on a few tiles, and
           the cells learned there - the border's looks among them - were the
           town's own, drawn again in the grass beyond its edge) */
        if (hero_copy && !(best >= 16 * 48 && best >= 2 * (hero_v > 0 ? hero_v : 0) + 16 * 24)) {
            best = 1; bx = hbx; by = hby;
        }
        if (getenv("DW4_WIDE_DEBUG"))
            fprintf(stderr, "dw4_wide: search %d,%d -> %d,%d (score %d) hero %d,%d off %d,%d\n", wx0, wy0, bx, by, best, E.hx, E.hy, E.dx, E.dy);
        /* no copy with the hero on screen: a scene looking away, if the
           picture says clearly where; else nothing to go by: near the hero */
        if (best >= (hero_copy ? 1 : 16 * 48)) { wx0 = bx; wy0 = by; }
    }
    E.cam_px = 8 * wx0 + fx; E.cam_py = 8 * wy0 + fy; E.cam_key = E.key; E.cam_ok = true;
    E.cam_hero = 2 * E.hx >= wx0 && 2 * E.hx < wx0 + 32 && 2 * E.hy >= wy0 && 2 * E.hy < wy0 + 30;
    *fx_ = fx; *fy_ = fy; *tx0_ = tx0; *ty0_ = ty0; *wx0_ = wx0; *wy0_ = wy0;
}

/* ---- the sides as a list of tiles ----
 * Each picture's side tiles (map tiles, then characters) are listed with their
 * CHR bytes and painted with the colours each line used (palette, greyscale,
 * emphasis: the battle flash is greyscale). The last map picture's list is
 * kept: when the game leaves the map (a door, stairs, a battle) the native
 * picture fades or spirals out while it is no longer a map we can match, so
 * the sides go on showing that picture, with the colours of the moment, until
 * the native picture is black. */
typedef struct { int16_t x, y; uint16_t pattern; uint8_t pal, flags, chr[16]; } SideTile;  /* pal 0-3 BG, 4-7 sprites */
#define EDGE_TILE 0x80      /* flags: over the native picture's first column */
#define MAX_SIDE 2048
static struct {
    SideTile t[MAX_SIDE]; int n;            /* this picture's */
    SideTile held[MAX_SIDE]; int nheld;     /* the last map picture's */
    uint8_t nt[30][32]; int tx0, ty0;       /* the native picture's tiles then */
    uint8_t ismap[30][32]; int maps;        /* which were map tiles (not windows, not flat), how many */
    bool have; int frames;
} P;

static void side_tile(int x, int y, uint16_t pattern, int pal, unsigned flags)
{
    if (P.n >= MAX_SIDE) return;
    SideTile *t = &P.t[P.n++];
    t->x = (int16_t)x; t->y = (int16_t)y; t->pattern = pattern; t->pal = (uint8_t)pal; t->flags = (uint8_t)flags;
    for (int i = 0; i < 16; i++) t->chr[i] = cyc_render_chr((uint16_t)(pattern + i));
}

static int paint_x0;        /* the native picture's canvas column */

static void paint_tile(uint32_t *out, int width, const SideTile *t, const uint8_t *pal, bool held)
{
    bool sprite = t->pal >= 4;
    for (int r = 0; r < 8; r++) {
        int py = t->y + r;
        if (py < 0 || py >= 240) continue;
        uint8_t m = cyc_render_line_mask(py);
        if (!(m & (sprite ? 0x10 : 0x08))) continue;
        int row = t->flags & CYC_TILE_VFLIP ? 7 - r : r;
        uint8_t lo = t->chr[row], hi = t->chr[row + 8];
        for (int c = 0; c < 8; c++) {
            int px = t->x + c;
            if (px < 0 || px >= width) continue;
            int b = t->flags & CYC_TILE_HFLIP ? c : 7 - c;
            int v = (lo >> b & 1) | (hi >> b & 1) << 1;
            if (v) out[py * width + px] = cyc_render_nes_color(pal[(sprite ? 16 + (t->pal - 4) * 4 : t->pal * 4) + v], m);
        }
    }
    if ((t->flags & EDGE_TILE) && !held && t->x >= paint_x0) return;   /* under the native picture: the game's own */
    if (held) cyc_render_hd_chr(t->pattern, t->chr);
    if (sprite) cyc_render_hd_sprite(t->x, t->y, t->pattern, t->pal - 4, t->flags);
    else cyc_render_hd_tile(t->x, t->y, t->pattern, t->pal);
}

/* The battle's spiral: when (frames after it starts) it reaches screen tile
 * (dx, dy) from the middle, fitted on the native picture (median error under
 * 2 frames): four arms turning, a little later further out. */
static double spiral_time(double dx, double dy)
{
    double r = sqrt(dx * dx + dy * dy), ph = fmod(atan2(dy, dx) - 0.4712 - 0.1 * r, M_PI / 2);
    if (ph < 0) ph += M_PI / 2;
    return 6.30 + 12.54 * ph + 0.404 * r;
}

/* skip (may be NULL): per tile, leave it out (the spiral reached it) */
static void paint(uint32_t *out, int width, int x0, const uint32_t *native, const SideTile *t, int n,
                  const uint8_t *skip, bool held, bool full)
{
    uint8_t pal[32];
    for (int i = 0; i < 32; i++) pal[i] = cyc_render_palette(i);
    paint_x0 = x0;
    for (int y = 0; y < 240; y++) {
        uint8_t m = cyc_render_line_mask(y);
        uint32_t back = m & 0x08 ? cyc_render_nes_color(pal[0], m) : 0xFF000000u;   /* background off: black */
        for (int x = 0; x < width; x++) out[y * width + x] = back;
    }
    for (int i = 0; i < n; i++) if (t[i].pal < 4 && !(skip && skip[i])) paint_tile(out, width, &t[i], pal, held);
    if (!full) for (int y = 0; y < 240; y++) memcpy(out + y * width + x0, native + y * 256, 256 * sizeof(uint32_t));
    /* held: the game no longer repairs its first column (the edge hook needs a map) */
    if (held) for (int i = 0; i < n; i++) if ((t[i].flags & EDGE_TILE) && !(skip && skip[i])) paint_tile(out, width, &t[i], pal, held);
    for (int i = 0; i < n; i++) if (t[i].pal >= 4 && !(skip && skip[i])) paint_tile(out, width, &t[i], pal, held);
}

/* A background tile of one colour (the spiral's black, a cleared screen). */
static bool flat_tile(uint8_t tile, uint16_t table)
{
    uint8_t lo = cyc_render_chr((uint16_t)(table + tile * 16)), hi = cyc_render_chr((uint16_t)(table + tile * 16 + 8));
    if ((lo != 0 && lo != 0xFF) || (hi != 0 && hi != 0xFF)) return false;
    for (int i = 1; i < 8; i++)
        if (cyc_render_chr((uint16_t)(table + tile * 16 + i)) != lo || cyc_render_chr((uint16_t)(table + tile * 16 + 8 + i)) != hi) return false;
    return true;
}

/* A tile that shows as plain black. */
static bool black_tile(uint8_t tile, int pal, uint16_t table)
{
    if (!flat_tile(tile, table)) return false;
    int v = (cyc_render_chr((uint16_t)(table + tile * 16)) & 1) | (cyc_render_chr((uint16_t)(table + tile * 16 + 8)) & 1) << 1;
    int c = cyc_render_palette(v ? (pal & 3) * 4 + v : 0) & 0x3F;
    return (c & 0x0F) >= 0x0D || c == 0x0F;
}

static int hold(uint32_t *out, int width, int x0, const uint32_t *native)
{
    static int debug = -1;
    if (debug < 0) debug = getenv("DW4_WIDE_DEBUG") != NULL;
    if (!P.have || ++P.frames > 240) { P.have = false; return 0; }
    /* still the map picture: its tiles, or ones turned to one colour (the spiral) */
    uint16_t table = cyc_render_line_bg_table(120);
    int same = 0, flat = 0, other = 0, same_map = 0;
    static double times[30 * 32];
    for (int j = 0; j < 30; j++)
        for (int k = 0; k < 32; k++) {
            uint8_t g = nt_tile(P.tx0 + k, mod(P.ty0 + j, 30));
            if (g == P.nt[j][k]) { same++; same_map += P.ismap[j][k]; }
            else if (flat_tile(g, table)) times[flat++] = spiral_time(k + 0.5 - 16, j + 0.5 - 15);
            else other++;
        }
    int lit = 0;
    for (int i = 0; i < 256 * 240; i += 7) {
        uint32_t c = native[i];
        lit += ((c >> 16 & 255) > 24) || ((c >> 8 & 255) > 24) || ((c & 255) > 24);
    }
    if (debug) fprintf(stderr, "dw4_wide: hold %d same %d flat %d other %d lit %d\n", P.frames, same, flat, other, lit);
    /* another screen, black, or the map gone (the spiral done: windows such as
       the status may stay up into the battle) */
    if (other > 96 || lit < 40 || same_map * 25 < P.maps) { P.have = false; return 0; }
    static uint8_t skip[MAX_SIDE];
    memset(skip, 0, (size_t)P.nheld);
    if (flat > 8) {
        /* the spiral: how far it has come, from the tiles it has turned */
        for (int i = 1; i < flat; i++)                                   /* sort (small) */
            for (int j = i; j > 0 && times[j] < times[j - 1]; j--) { double x = times[j]; times[j] = times[j - 1]; times[j - 1] = x; }
        double now = times[flat * 9 / 10];
        for (int i = 0; i < P.nheld; i++) {
            const SideTile *t = &P.held[i];
            skip[i] = spiral_time((t->x - x0 + 4) / 8.0 - 16, (t->y + 4) / 8.0 - 15) <= now;
        }
    }
    paint(out, width, x0, native, P.held, P.nheld, skip, true, false);
    return 1;
}

static bool check_wide;

/* A picture of one tile everywhere (a plain field the game fills without its
 * map, a cleared screen): the sides continue it. Windows don't count. */
static int uniform(uint32_t *out, int width, int x0, const uint32_t *native)
{
    int sx = cyc_render_line_scroll_x(120), sy = mod(cyc_render_line_scroll_y(120) - 120, 240);
    int tx0 = sx >> 3, ty0 = sy >> 3, fx = sx & 7, fy = sy & 7;
    int t = -1, pal = -1, n = 0;
    for (int j = 2; j < 28; j++)
        for (int k = 1; k < 31; k++) {
            uint8_t g = nt_tile(tx0 + k, mod(ty0 + j, 30));
            if (g >= 1 && g <= 0x8B) continue;                         /* window, text */
            if (g == 0 && in_window(tx0 + k, mod(ty0 + j, 30), 0)) continue;
            int p = nt_pal(tx0 + k, mod(ty0 + j, 30));
            if (t < 0) { t = g; pal = p; }
            else if (g != t || p != pal) return 0;
            n++;
        }
    if (n < 200) return 0;
    uint16_t table = cyc_render_line_bg_table(120);
    P.n = 0;
    for (int j = 0; j <= 30; j++)
        for (int cx = x0 - fx - 8 * ((x0 + 7) / 8 + 1); cx < width; cx += 8) {
            if (cx + 8 <= 0 || (cx >= x0 + 8 && cx + 8 <= x0 + 256)) continue;
            side_tile(cx, 8 * j - fy, (uint16_t)(table + t * 16), pal, cx + 8 > x0 && cx < x0 + 8 ? EDGE_TILE : 0);
        }
    paint(out, width, x0, native, P.t, P.n, NULL, false, false);
    P.have = false;
    return 1;
}

static int compose(uint32_t *out, int width, int height, int x0, const uint32_t *native, void *user)
{
    (void)user; (void)height;
    /* nothing read from the game yet (the first frames; edge repair off) */
    if (!E.enabled || !E.ram || !E.wram || !E.ciram) return 0;
    if (!E.valid) {                                        /* not a map: one tile everywhere, the last one fading, or pillarboxed */
        if (P.have) { int h = hold(out, width, x0, native); if (h) return h; }
        return uniform(out, width, x0, native);
    }
    static int ck = -1;
    if (ck < 0) ck = getenv("DW4_WIDE_CHECK") != NULL;
    check_wide = ck;
    static int fl = -1;
    if (fl < 0) fl = getenv("DW4_WIDE_FULL") != NULL;     /* debug: draw the native 256 from the map too */
    bool full = fl;
    int fx, fy, tx0, ty0, wx0, wy0;
    locate(E.need_search, &fx, &fy, &tx0, &ty0, &wx0, &wy0);
    E.need_search = false;
    /* does the native picture show this map here? (a battle can leave the
       map's tiles in the nametable while the screen shows the battle) */
    {
        int n = 0, bad = 0, drawn = 0;
        uint16_t tb = cyc_render_line_bg_table(120);
        for (int j = 2; j < 28; j += 2)
            for (int k = 2; k < 30; k += 2) {
                int t = map_quarter(wx0 + k, wy0 + j);
                uint8_t g = nt_tile(tx0 + k, mod(ty0 + j, 30));
                if (t < 0 || !E.map_tile[g] || (g == 0 && in_window(tx0 + k, mod(ty0 + j, 30), 0))) continue;
                n++; bad += (t & 0xFF) != g;
                if ((t & 0xFF) != g && getenv("DW4_WIDE_DEBUG") && getenv("DW4_WIDE_DEBUG")[0] == '3')
                    fprintf(stderr, "  disagree cell %d,%d value %02X room %02X: map %02X screen %02X\n", floordiv(wx0 + k, 2), floordiv(wy0 + j, 2),
                            cell_key(floordiv(wx0 + k, 2), floordiv(wy0 + j, 2)), E.room46, t & 0xFF, g);
                /* tiles that show something: a battle's black screen agrees
                   with every dark cell of a cave (and the map's characters
                   were drawn in the sides, with the battle's tiles) */
                drawn += (t & 0xFF) == g && !black_tile(g, t >> 8, tb);
            }
        if (n < 20 || bad * (E.overworld ? 4 : 8) > n || drawn < 6) {
            if (getenv("DW4_EDGES_DEBUG")) fprintf(stderr, "dw4_wide: picture disagrees %d/%d\n", bad, n);
            if (P.have) { int h = hold(out, width, x0, native); if (h) return h; }
            return uniform(out, width, x0, native);
        }
    }
    uint16_t table = cyc_render_line_bg_table(120);
    P.n = 0;
    int k0 = floordiv(fx - x0, 8) - 1, k1 = floordiv(width - x0 + fx, 8) + 1;
    for (int j = 0; j <= 30; j++) {
        int cy = 8 * j - fy;
        for (int k = k0; k <= k1; k++) {
            int cx = x0 - fx + 8 * k;
            /* the margins, and the native picture's first column (the game hides it;
               a held picture shows it, see hold) */
            if (cx + 8 <= 0 || cx >= width || (!full && cx >= x0 + 8 && cx + 8 <= x0 + 256)) continue;
            int t = map_quarter(wx0 + k, wy0 + j);
            if (t < 0) continue;
            uint16_t pattern = (uint16_t)(table + (t & 0xFF) * 16);
            side_tile(cx, cy, pattern, t >> 8, cx + 8 > x0 && cx < x0 + 8 ? EDGE_TILE : 0);
        }
    }
    if (check_wide) {
        /* the same formula over the native picture: how often it disagrees
           with what the game drew (map tiles only, not the edge rows) */
        int n = 0, bad = 0;
        for (int j = 2; j < 28; j++)
            for (int k = 2; k < 30; k++) {
                int t = map_quarter(wx0 + k, wy0 + j);
                uint8_t g = nt_tile(tx0 + k, mod(ty0 + j, 30));
                if (t < 0 || !E.map_tile[g] || (g == 0 && in_window(tx0 + k, mod(ty0 + j, 30), 0))) continue;
                n++; bad += (t & 0xFF) != g;
                if ((t & 0xFF) != g && getenv("DW4_WIDE_CHECK")[0] == '2' && !(k & 1) && !(j & 1)) {
                    int wx = wx0 + k, wy = wy0 + j, c = cell_key(floordiv(wx, 2), floordiv(wy, 2));
                    fprintf(stderr, "  diff k%d j%d cell %d,%d key %02X cur %d room %d/%d nt %02X%02X%02X%02X looks",
                            k, j, floordiv(wx, 2), floordiv(wy, 2), c, E.cur[c], c >> 5, E.room[c >> 5].state,
                            nt_tile(tx0 + k, mod(ty0 + j, 30)), nt_tile(tx0 + k + 1, mod(ty0 + j, 30)),
                            nt_tile(tx0 + k, mod(ty0 + j + 1, 30)), nt_tile(tx0 + k + 1, mod(ty0 + j + 1, 30)));
                    fprintf(stderr, " want %02X room46 %02X/%02X meta20 %02X meta21 %02X", t & 0xFF, E.room46, E.ram[0x46], E.wram[0x1680], E.wram[0x1684]);
                    for (int l = 0; l < LOOKS; l++) if (E.look[c][l].conf)
                        fprintf(stderr, " %02X%02X%02X%02X:%d", E.look[c][l].q[0], E.look[c][l].q[1], E.look[c][l].q[2], E.look[c][l].q[3], E.look[c][l].conf);
                    fprintf(stderr, "\n");
                }
            }
        if (getenv("DW4_WIDE_CHECK")[0] == '2') {
            fprintf(stderr, "  hero screen tile %d,%d fine %d,%d 3E %d\n", mod(2 * E.hx + E.dx - tx0, 64), mod(2 * E.hy + E.dy - ty0, 30), fx, fy, E.ram[0x3E]);
            int nb = 0; for (int a = 0; a < 256; a++) nb += E.border[a >> 4][a & 15].ok;
            fprintf(stderr, "  border looks %d cam %d,%d valid_frames %d\n", nb, E.cam_px, E.cam_py, E.valid_frames);
        }
        fprintf(stderr, "dw4_wide: check %s %d/%d differ\n", E.overworld ? worlds[E.world].name : "town", bad, n);
    }
    /* canvas pixel of map cell (0, 0)'s top-left: map tile column 0 is k = -wx0 */
    draw_characters(out, width, x0, x0 - fx - 8 * wx0 + CHAR_DX, -fy - 8 * wy0 + CHAR_DY);
    paint(out, width, x0, native, P.t, P.n, NULL, false, full);
    /* kept for the way out of this map */
    memcpy(P.held, P.t, (size_t)P.n * sizeof P.t[0]); P.nheld = P.n;
    P.tx0 = tx0; P.ty0 = ty0;
    for (int j = 0; j < 30; j++)
        for (int k = 0; k < 32; k++) P.nt[j][k] = nt_tile(tx0 + k, mod(ty0 + j, 30));
    P.maps = 0;
    for (int j = 0; j < 30; j++)
        for (int k = 0; k < 32; k++) P.maps += P.ismap[j][k] = E.map_tile[P.nt[j][k]] && !flat_tile(P.nt[j][k], table);
    P.have = true; P.frames = 0;
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
static const uint8_t *frame_sprites(int i, int f) { return objsnap + 0x1200 + 64 * (objsnap[0xFE0 + i] & 15) + f * 8; }

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
        const uint8_t *w = objsnap;
        int X = w[0xF60 + i], Y = w[0xF80 + i], PX = w[0xFA0 + i], PY = w[0xFC0 + i];
        /* the game's own rule (bank $3E $E0CF/$E16F): drawn when $7020 has
           neither bit 7 nor bit 4, and the room it stands in ($7140 bits 5-7)
           is the hero's ($46): people in a roofed or dark room stay hidden */
        if (w[0x1020 + i] & 0x90) continue;
        if ((w[0x1140 + i] & 0xE0) != (E.ram[0x46] & 0xE0)) continue;
        if (E.overworld) {
            /* world cells (a byte each way): the copy nearest the hero */
            int dx = (int8_t)(uint8_t)(X - E.hx), dy = (int8_t)(uint8_t)(Y - E.hy);
            int pdx = (int8_t)(uint8_t)(PX - X), pdy = (int8_t)(uint8_t)(PY - Y);
            X = E.hx + dx; Y = E.hy + dy;
            /* the previous cell only counts when it is next door (it also holds where the party came out) */
            if (abs(pdx) + abs(pdy) == 1) { PX = X + pdx; PY = Y + pdy; } else { PX = X; PY = Y; }
        } else if (X >= 0x80 || Y >= 0x80) continue;        /* not on the map */
        /* walking: each character's own progress, in 1/16 pixels from the
           left/upper of its two cells ($7100 X, $7120 Y) */
        int rem = X != PX || Y != PY;
        int face = w[0x1000 + i] & 3;                      /* 0 up 1 right 2 down 3 left */
        /* top-left of the character in canvas pixels (CHAR_DX/DY: where the game puts sprites in a cell) */
        /* (the progress can still be counting the last pixels when the cells agree) */
        int cx = ox + 16 * (X < PX ? X : PX) + (w[0x1100 + i] >> 4);
        int cy = oy + 16 * (Y < PY ? Y : PY) + (w[0x1120 + i] >> 4);
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
        if (debug && shown >= 0 && nx >= 8 && nx + 16 <= 248 && cy >= 16 && cy + 16 <= 224) {
            const uint8_t *fs = frame_sprites(i, shown);
            int bd = 999, bx = 0, by = 0;
            for (int s2 = 0; s2 < 64; s2++) {
                const uint8_t *o = oam + 4 * s2;
                if (o[0] >= 0xEF || o[1] != fs[0]) continue;
                int ddx = o[3] - nx, ddy = o[0] + 1 - cy;
                if (abs(ddx) + abs(ddy) < bd) { bd = abs(ddx) + abs(ddy); bx = ddx; by = ddy; }
            }
            fprintf(stderr, "dw4_wide: dpos %d %d %d moving %d X %02X PX %02X Y %02X PY %02X off %02X %02X 3E %02X/%02X slot %02X 7000 %02X 7040 %02X\n", i, bx, by, rem,
                    X, PX, Y, PY, w[0x1100 + i], w[0x1120 + i], E.ram3e, E.ram[0x3E], w[0xFE0 + i], w[0x1000 + i], w[0x1040 + i]);
        }
        /* a character the game also draws (part of it on its screen): take its
           exact place from the game's sprites, so the two halves meet (a lag
           frame can leave the game's sprite a pixel behind the table) */
        if (shown >= 0) {
            const uint8_t *fs = frame_sprites(i, shown);
            int bd = 99, bx = 0, by = 0;
            for (int k = 0; k < 4; k++)
                for (int s2 = 0; s2 < 64; s2++) {
                    const uint8_t *o = oam + 4 * s2;
                    if (o[0] >= 0xEF || o[1] != fs[2 * k] || (o[2] & 0xC3) != (fs[2 * k + 1] & 0xC3)) continue;
                    int ddx = o[3] - (nx + 8 * (k & 1)), ddy = o[0] + 1 - (cy + 8 * (k >> 1));
                    if (abs(ddx) <= 2 && abs(ddy) <= 2 && abs(ddx) + abs(ddy) < bd) { bd = abs(ddx) + abs(ddy); bx = ddx; by = ddy; }
                }
            if (bd < 99) { cx += bx; cy += by; nx += bx; }
        }
        /* both steps alike (the frames share their sprites): no say on the step */
        bool step_known = shown >= 0 && hits[shown ^ 1] < hits[shown];
        if (debug && shown < 0 && rem && nx >= 8 && nx + 16 <= 248 && cy >= 16 && cy + 16 <= 224) {
            int bd = 999, bx = 0, by = 0;
            for (int f = 0; f < 8; f++) {
                const uint8_t *fs = frame_sprites(i, f);
                for (int s2 = 0; s2 < 64; s2++) {
                    const uint8_t *o = oam + 4 * s2;
                    if (o[0] >= 0xEF || o[1] != fs[0]) continue;
                    int ddx = o[3] - nx, ddy = o[0] + 1 - cy;
                    if (abs(ddx) + abs(ddy) < bd) { bd = abs(ddx) + abs(ddy); bx = ddx; by = ddy; }
                }
            }
            fprintf(stderr, "dw4_wide: miss %d X %02X PX %02X Y %02X PY %02X off %02X %02X 3E %02X d %d %d\n", i, X, PX, Y, PY,
                    w[0x1100 + i], w[0x1120 + i], E.ram[0x3E], bx, by);
        }
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
            side_tile(sx, sy, (uint16_t)(table + t * 16), 4 + (a & 3), fl);
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
    memset(E.look, 0, sizeof E.look); memset(E.room, 0, sizeof E.room); E.room_last = 0; memset(E.border, 0, sizeof E.border); memset(E.cellmem, 0, sizeof E.cellmem);
    /* (also after loading a state: nothing seen before it holds) */
    E.valid = false; E.key = 0; E.search_wait = 0; P.have = false;
    E.cam_ok = false; E.need_search = false; E.recheck = 0;
    memset(E.cur, -1, sizeof E.cur);
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
