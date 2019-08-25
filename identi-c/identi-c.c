#include <gtk/gtk.h>
#include <math.h>

enum {
    NODE_RADIUS = 20,
    TOP_MARGIN = 100,
    LEFT_MARGIN = 100,
    NODE_X_STEP = 45,
    NODE_Y_STEP = 45,
};

const double canvas_color[] =  //
    {0.5, 0.6, 0.8};

enum {
    STATE_DEFAULT,
    STATE_MOVING_NODE,
};

#define IDENTIC_APP_TYPE (identic_app_get_type())
#define IDENTIC_APP_WINDOW_TYPE (identic_app_window_get_type())

G_DECLARE_FINAL_TYPE(IdenticApp, identic_app, IDENTIC, APP, GtkApplication);
G_DECLARE_FINAL_TYPE(IdenticAppWindow, identic_app_window, IDENTIC, APP_WINDOW,
                     GtkApplicationWindow);

static IdenticAppWindow *
identic_app_window_new(IdenticApp *app);

struct _IdenticApp {
    GtkApplication parent;
    GHashTable *prg;
    GHashTable *line_length;
    int max_x;
    int max_y;
    IdenticAppWindow *wnd;
};

struct _IdenticAppWindow {
    GtkApplicationWindow parent;
    IdenticApp *app;
    GtkWidget *drawing_area;

    gboolean cache_valid;

    struct {
        int state;
        int character;
        struct {
            int x;
            int y;
        } highlighted;
        struct {
            int x;
            int y;
        } mouse;
    } current;
};

G_DEFINE_TYPE(IdenticApp, identic_app, GTK_TYPE_APPLICATION);
G_DEFINE_TYPE(IdenticAppWindow, identic_app_window,
              GTK_TYPE_APPLICATION_WINDOW);

static void
identic_app_reset_program(IdenticApp *app)
{
    if (app->prg)
        g_hash_table_unref(app->prg);
    if (app->line_length)
        g_hash_table_unref(app->line_length);

    app->prg = g_hash_table_new(g_direct_hash, g_direct_equal);
    app->line_length = g_hash_table_new(g_direct_hash, g_direct_equal);
}

static void
identic_app_init(IdenticApp *app)
{
    identic_app_reset_program(app);
}

static gpointer
xy_to_key(int x, int y)
{
    return GINT_TO_POINTER((y << 16) + x);
}

static int
key_to_x(gpointer key)
{
    return GPOINTER_TO_INT(key) & 0xffff;
}

static int
key_to_y(gpointer key)
{
    return GPOINTER_TO_INT(key) >> 16;
}

static void
identic_app_load_string(IdenticApp *app, const char *str)
{
    identic_app_reset_program(app);

    int x = 0;
    int y = 0;
    app->max_x = 0;
    app->max_y = 0;
    for (const char *ptr = str; *ptr != 0; ptr = g_utf8_next_char(ptr)) {
        if (*ptr == '\n') {
            g_hash_table_insert(app->line_length, GINT_TO_POINTER(y),
                                GINT_TO_POINTER(x));
            x = 0;
            y += 1;
            continue;
        }

        g_hash_table_insert(
            app->prg, xy_to_key(x, y),
            GINT_TO_POINTER((unsigned int)g_utf8_get_char(ptr)));
        x += 1;
        app->max_x = MAX(app->max_x, x);
        app->max_y = MAX(app->max_y, y);
    }
}

static void
identic_app_save_to_file(IdenticApp *app, const char *filename)
{
    GString *s = g_string_new(NULL);

    for (int y = 0; y <= app->max_y; y++) {
        int line_length = GPOINTER_TO_INT(
            g_hash_table_lookup(app->line_length, GINT_TO_POINTER(y)));
        for (int x = 0; x < line_length; x++) {
            int c =
                GPOINTER_TO_INT(g_hash_table_lookup(app->prg, xy_to_key(x, y)));
            if (c == 0)
                c = ' ';
            g_string_append_unichar(s, c);
        }
        g_string_append_c(s, '\n');
    }

    g_file_set_contents(filename, s->str, -1, NULL);
}

static void
identic_app_replace_char(IdenticApp *app, int x, int y, int c)
{
    g_hash_table_insert(app->prg, xy_to_key(x, y), GINT_TO_POINTER(c));

    int old_line_length = GPOINTER_TO_INT(
        g_hash_table_lookup(app->line_length, GINT_TO_POINTER(y)));

    int new_line_length = MAX(x + 1, old_line_length);
    g_hash_table_insert(app->line_length, GINT_TO_POINTER(y),
                        GINT_TO_POINTER(new_line_length));

    app->max_x = MAX(app->max_x, x);
    app->max_y = MAX(app->max_y, y);
}

static void
identic_app_activate(GApplication *g_app)
{
    IdenticApp *app = IDENTIC_APP(g_app);
    app->wnd = identic_app_window_new(app);
#if 0
        identic_app_load_string(app,
                                "#include <stdio.h>\n"
                                "int main(void) {\n"
                                "  printf(\"Hello World!\\n\");\n"
                                "  return 2;\n"
                                "}\n");
#endif
    gtk_window_present(GTK_WINDOW(app->wnd));
}

static void
identic_app_class_init(IdenticAppClass *class)
{
    G_APPLICATION_CLASS(class)->activate = identic_app_activate;
}

static IdenticApp *
identic_app_new(void)
{
    return g_object_new(IDENTIC_APP_TYPE,  //
#if 0
                        "application-id", "private.identi-c",  //
#endif
                        "flags", 0,  //
                        NULL);
}

static void
identic_app_window_init(IdenticAppWindow *window)
{
    memset(&window->current, 0, sizeof(window->current));
    window->current.state = STATE_DEFAULT;
}

static void
identic_app_window_class_init(IdenticAppWindowClass *class)
{
}

static void
prepare_node_path(cairo_t *cr)
{
    cairo_new_sub_path(cr);
    cairo_move_to(cr, 0, 0);
    cairo_line_to(cr, 0, NODE_RADIUS);
    cairo_arc_negative(cr, NODE_RADIUS, NODE_RADIUS, NODE_RADIUS, -M_PI,
                       -M_PI / 2);
    cairo_close_path(cr);
}

static void
draw_node_border(cairo_t *cr, double x, double y)
{
    cairo_save(cr);
    cairo_translate(cr, x, y);
    prepare_node_path(cr);
    cairo_set_source_rgb(cr, 0, 0, 0);
    cairo_set_line_width(cr, 2);
    cairo_stroke(cr);
    cairo_restore(cr);
}

static void
draw_node(cairo_t *cr, double x, double y, unsigned int c)
{
    char text[2] = {c, 0};

    // TODO: Unicode.
    if (c > 128)
        return;

    cairo_save(cr);
    cairo_translate(cr, x, y);
    prepare_node_path(cr);
    cairo_set_source_rgb(cr, 0.6, 0.7, 0.9);
    cairo_fill(cr);

    cairo_text_extents_t e;
    cairo_set_font_size(cr, 24);
    cairo_text_extents(cr, text, &e);
    cairo_move_to(cr, NODE_RADIUS - (e.width / 2 + e.x_bearing),
                  NODE_RADIUS + 7);
    cairo_set_source_rgb(cr, 0.2, 0.1, 0.4);
    cairo_show_text(cr, text);
    cairo_restore(cr);
}

static void
identic_app_window_invalidate_cache(IdenticAppWindow *wnd)
{
    wnd->cache_valid = FALSE;
    gtk_widget_set_size_request(
        wnd->drawing_area, LEFT_MARGIN + (wnd->app->max_x + 1) * NODE_X_STEP,
        TOP_MARGIN + (wnd->app->max_y + 1) * NODE_Y_STEP);
}

static gboolean
identic_app_window_drawing_area_draw(GtkWidget *widget, cairo_t *cr,
                                     gpointer data)
{
    IdenticAppWindow *wnd = data;
    IdenticApp *app = wnd->app;
    GHashTableIter iter;
    gpointer key, val;

    cairo_set_source_rgb(cr, canvas_color[0], canvas_color[1], canvas_color[2]);
    cairo_paint(cr);

    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_set_line_width(cr, 3);
    cairo_move_to(cr, LEFT_MARGIN + NODE_RADIUS - NODE_X_STEP,
                  TOP_MARGIN + NODE_RADIUS);
    cairo_line_to(cr, LEFT_MARGIN + NODE_RADIUS - NODE_X_STEP,
                  TOP_MARGIN + NODE_RADIUS + app->max_y * NODE_Y_STEP);

    g_hash_table_iter_init(&iter, app->line_length);
    while (g_hash_table_iter_next(&iter, &key, &val)) {
        int y = GPOINTER_TO_INT(key);
        int line_length = GPOINTER_TO_INT(val);

        cairo_move_to(cr, LEFT_MARGIN + NODE_RADIUS - NODE_X_STEP,
                      TOP_MARGIN + NODE_RADIUS + y * NODE_Y_STEP);
        cairo_rel_line_to(cr, NODE_X_STEP * (line_length), 0);
    }

    cairo_stroke(cr);

    g_hash_table_iter_init(&iter, app->prg);
    while (g_hash_table_iter_next(&iter, &key, &val)) {
        char c = GPOINTER_TO_INT(val);

        draw_node(cr, LEFT_MARGIN + key_to_x(key) * NODE_X_STEP,
                  TOP_MARGIN + key_to_y(key) * NODE_Y_STEP, c);
    }

    if (wnd->current.state == STATE_MOVING_NODE) {
        int x = wnd->current.highlighted.x;
        int y = wnd->current.highlighted.y;
        draw_node_border(cr, LEFT_MARGIN + x * NODE_X_STEP,
                         TOP_MARGIN + y * NODE_Y_STEP);

        draw_node(cr, wnd->current.mouse.x - 2 * NODE_RADIUS,
                  wnd->current.mouse.y - 2 * NODE_RADIUS,
                  wnd->current.character);
    }

    return TRUE;
}

static gboolean
identic_app_window_drawing_area_mouse_move(GtkWidget *widget, GdkEvent *event,
                                           gpointer data)
{
    IdenticAppWindow *wnd = data;

    int x = (event->motion.x - LEFT_MARGIN - NODE_RADIUS) / NODE_X_STEP;
    int y = (event->motion.y - TOP_MARGIN - NODE_RADIUS) / NODE_Y_STEP;

    if (x >= 0 && y >= 0) {
        wnd->current.highlighted.x = x;
        wnd->current.highlighted.y = y;
    }

    wnd->current.mouse.x = event->motion.x;
    wnd->current.mouse.y = event->motion.y;

    gtk_widget_queue_draw(wnd->drawing_area);
    return TRUE;
}

static void
identic_app_window_load_file(IdenticAppWindow *wnd, const char *filename)
{
    IdenticApp *app = wnd->app;

    char *contents;
    if (g_file_get_contents(filename, &contents, NULL, NULL)) {
        identic_app_load_string(app, contents);
        identic_app_window_invalidate_cache(wnd);
        g_free(contents);
    }
}

static gboolean
identic_app_window_load_button_pressed(GtkWidget *btn, GdkEvent *event,
                                       gpointer data)
{
    IdenticAppWindow *wnd = data;
    GtkWidget *dialog = gtk_file_chooser_dialog_new(                 //
        "Open file", GTK_WINDOW(wnd), GTK_FILE_CHOOSER_ACTION_OPEN,  //
        "_Cancel", GTK_RESPONSE_CANCEL,                              //
        "_Open", GTK_RESPONSE_ACCEPT,                                //
        NULL);                                                       //

    GtkFileFilter *ic_filter = gtk_file_filter_new();
    gtk_file_filter_set_name(ic_filter, "Identi-C source code files (*.ic)");
    gtk_file_filter_add_pattern(ic_filter, "*.ic");

    GtkFileFilter *any_file_filter = gtk_file_filter_new();
    gtk_file_filter_set_name(any_file_filter, "All files (*)");
    gtk_file_filter_add_pattern(any_file_filter, "*");

    gtk_file_chooser_add_filter(GTK_FILE_CHOOSER(dialog), ic_filter);
    gtk_file_chooser_add_filter(GTK_FILE_CHOOSER(dialog), any_file_filter);

    GtkFileChooser *chooser = GTK_FILE_CHOOSER(dialog);
    char *cwd = g_get_current_dir();
    gtk_file_chooser_set_current_folder(chooser, cwd);
    free(cwd);

    gint res = gtk_dialog_run(GTK_DIALOG(dialog));
    if (res == GTK_RESPONSE_ACCEPT) {
        char *filename =
            gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(dialog));
        identic_app_window_load_file(wnd, filename);
        g_free(filename);
    }

    gtk_widget_destroy(dialog);
    return TRUE;
}

static gboolean
identic_app_window_run_button_pressed(GtkWidget *btn, GdkEvent *event,
                                      gpointer data)
{
    IdenticAppWindow *wnd = data;
    identic_app_save_to_file(wnd->app, "/tmp/identi-c-source.c");

    // TODO: remove hardcoded names and paths?
    g_file_set_contents(
        "/tmp/identi-c-run.sh",
        "gcc /tmp/identi-c-source.c -o /tmp/identi-c-executable "
        "`pkg-config --cflags --libs gtk+-3.0` && "
        "/tmp/identi-c-executable; echo; echo 'press enter to continue...'; "
        "read placeholder\n",
        -1, NULL);

    system("xfce4-terminal -x sh /tmp/identi-c-run.sh");
    return TRUE;
}

static gboolean
identic_app_window_drawing_area_mouse_button_pressed(GtkWidget *widget,
                                                     GdkEvent *event,
                                                     gpointer data)
{
    IdenticAppWindow *wnd = data;

    if (wnd->current.state == STATE_MOVING_NODE) {
        identic_app_replace_char(wnd->app, wnd->current.highlighted.x,
                                 wnd->current.highlighted.y,
                                 wnd->current.character);
        wnd->current.state = STATE_DEFAULT;
        gtk_widget_queue_draw(wnd->drawing_area);
    }

    return TRUE;
}

static gboolean
identic_app_window_key_pressed(GtkWidget *widget, GdkEvent *event,
                               gpointer data)
{
    IdenticAppWindow *wnd = data;

    if (wnd->current.state == STATE_DEFAULT && event->key.string[0] != 0) {
        wnd->current.state = STATE_MOVING_NODE;
        wnd->current.character = g_utf8_get_char(event->key.string);
        gtk_widget_queue_draw(wnd->drawing_area);
    }
    return TRUE;
}

static IdenticAppWindow *
identic_app_window_new(IdenticApp *app)
{
    IdenticAppWindow *wnd =
        g_object_new(IDENTIC_APP_WINDOW_TYPE, "application", app, NULL);
    wnd->app = app;

    gtk_window_set_title(GTK_WINDOW(wnd), "Identi-C");

    GtkWidget *vbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    gtk_container_add(GTK_CONTAINER(wnd), vbox);

    GtkWidget *hbox = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 5);
    gtk_box_pack_start(GTK_BOX(vbox), hbox, FALSE, FALSE, 5);
    g_object_set(hbox, "margin-left", 5, NULL);

    GtkWidget *btn_load = gtk_label_new("📁");
    gtk_widget_add_events(btn_load, GDK_BUTTON_PRESS_MASK);
    gtk_widget_set_has_window(btn_load, TRUE);
    g_signal_connect(btn_load, "button-press-event",
                     G_CALLBACK(identic_app_window_load_button_pressed), wnd);

    GtkWidget *btn_save = gtk_label_new("💾");
    gtk_widget_set_events(btn_save, GDK_BUTTON_PRESS_MASK);
    gtk_widget_set_has_window(btn_save, TRUE);
    // TODO: g_signal_connect(btn_save, "button-press-event",
    //                 G_CALLBACK(identic_app_window_save_button_pressed), wnd);

    GtkWidget *btn_run = gtk_label_new("▶");
    gtk_widget_set_events(btn_run, GDK_BUTTON_PRESS_MASK);
    gtk_widget_set_has_window(btn_run, TRUE);
    g_signal_connect(btn_run, "button-press-event",
                     G_CALLBACK(identic_app_window_run_button_pressed), wnd);

    gtk_box_pack_start(GTK_BOX(hbox), btn_load, FALSE, FALSE, 15);
    gtk_box_pack_start(GTK_BOX(hbox), btn_save, FALSE, FALSE, 15);
    gtk_box_pack_start(GTK_BOX(hbox), btn_run, FALSE, FALSE, 15);

    GtkWidget *scrolled_window = gtk_scrolled_window_new(NULL, NULL);
    gtk_widget_set_size_request(scrolled_window, 1280, 720);
    gtk_scrolled_window_set_propagate_natural_width(
        GTK_SCROLLED_WINDOW(scrolled_window), TRUE);

    GtkWidget *drawing_area = gtk_drawing_area_new();
    gtk_container_add(GTK_CONTAINER(scrolled_window), drawing_area);
    gtk_widget_add_events(drawing_area, GDK_POINTER_MOTION_MASK);
    gtk_widget_add_events(drawing_area, GDK_BUTTON_PRESS_MASK);
    gtk_widget_add_events(drawing_area, GDK_KEY_PRESS_MASK);
    wnd->drawing_area = drawing_area;

    gtk_box_pack_start(GTK_BOX(vbox), scrolled_window, TRUE, TRUE, 0);

    g_signal_connect(drawing_area, "draw",
                     G_CALLBACK(identic_app_window_drawing_area_draw), wnd);
    g_signal_connect(drawing_area, "motion-notify-event",
                     G_CALLBACK(identic_app_window_drawing_area_mouse_move),
                     wnd);
    g_signal_connect(
        drawing_area, "button-press-event",
        G_CALLBACK(identic_app_window_drawing_area_mouse_button_pressed), wnd);
    g_signal_connect(wnd, "key-press-event",
                     G_CALLBACK(identic_app_window_key_pressed), wnd);

    gtk_widget_set_size_request(drawing_area, 1280, 720);

    gtk_widget_show_all(GTK_WIDGET(wnd));

    return wnd;
}

int
main(int argc, char *argv[])
{
    return g_application_run(G_APPLICATION(identic_app_new()), argc, argv);
}
