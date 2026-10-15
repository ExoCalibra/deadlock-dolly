// ImGui presentation only. Called with the overlay context current and its render lock held.
#pragma once
#include "dolly_editor.hpp"
#include "dolly_bone_picker.hpp"
#include "dolly_visualization.hpp"
#include "imgui.h"
#include <memory>
struct ImGuiSettingsHandler;

namespace dolly {
// Borrowed renderer operations; the panel never creates/releases a GPU resource.
struct PickerPortrait {
    void (*reset)() noexcept;
    void (*update)(const PickerFrame&) noexcept;
    ImTextureID (*texture)() noexcept;
};

// One presentation owner per overlay context; existing per-widget static edit
// caches remain process-lived to preserve device-loss behavior.
class OverlayPanel {
public:
    bool lite_mode() const noexcept { return lite_mode_; }
    void style_panel();
    void initialize_layout();
    void load_panel_fonts(float scale);
    // Font pointers borrow the current ImGui atlas. Guide preference and widget
    // edit caches deliberately survive device recreation, as they did before.
    void reset_fonts() noexcept {
        panel_font = heading_font = title_font = nullptr;
        panel_scale = 1.0f;
    }
    bool guides_visible(const EditorSnapshot& state) noexcept;
    bool framing_grid_visible(const EditorSnapshot& state) noexcept;
    void draw_path_guides(const EditorSnapshot& state,
                          const std::shared_ptr<const VisualizationPath>& path);
    void draw_framing_grid(const EditorSnapshot& state);
    bool shader_notice_visible(const EditorSnapshot& state) const noexcept;
    void draw_shader_notice();
    bool lite_campaths_visible(const EditorSnapshot& state) const noexcept;
    void draw_lite_campaths(const EditorSnapshot& state);
    void draw_lite_timeline(const EditorSnapshot& state);
    void draw_panel(const EditorSnapshot& state);
    void draw_bone_picker(const EditorSnapshot& state, const PickerPortrait& portrait);
    // The Object Picker is its own mode and its own right-side window, entered
    // only by its bindable key. It needs no GPU resource (proxy wireframes).
    void draw_object_picker(const EditorSnapshot& state);
    void reset_guides() noexcept { guide_geometry.line_count = guide_geometry.label_count = 0; }
    std::size_t guide_lines() const noexcept { return guide_geometry.line_count; }
    std::size_t guide_labels() const noexcept { return guide_geometry.label_count; }
    // Last drawn Shot-timeline rect (screen coordinates) and committed tick
    // drags; the smoke test reads these through overlay diagnostics.
    float timeline_x0() const noexcept { return timeline_x0_; }
    float timeline_x1() const noexcept { return timeline_x1_; }
    float timeline_y() const noexcept { return timeline_y_; }
    std::uint64_t timeline_drags() const noexcept { return timeline_drags_; }
    float timeline_view_start() const noexcept { return timeline_view_start_; }
    float timeline_view_end() const noexcept { return timeline_view_end_; }

private:
    bool layout_editing_ = false, reduced_motion_ = false, classic_layout_ = false, layout_custom_ = false;
    bool compact_controls_ = false, compact_paths_ = false, card_open_ = false;
    bool editor_custom_ = false, editor_position_pending_ = false, editor_dragging_ = false;
    ImVec2 editor_position_{};
    ImVec2 drag_start_[3]{}, drag_mouse_[3]{}, outer_position_[2]{};
    bool outer_position_pending_[2]{};
    unsigned section_slots_[5][4]={{0,1,2,3},{0,1,2,3},{0,1,2,3},{0,1,2,3},{0,1,2,3}};
    float section_heights_[5][4]={{230,160,0,0},{170,200,0,0},{150,330,0,0},{290,140,140,160},{140,230,150,120}};
    ImVec2 section_positions_[4]{};
    unsigned section_columns_[4]{}, card_index_ = 0;
    int section_column_pref_[5][4]={{-1,-1,-1,-1},{-1,-1,-1,-1},{-1,-1,-1,-1},{-1,-1,-1,-1},{-1,-1,-1,-1}};
    float column_weights_[5][3]={{1,1,1},{1,1,1},{1,1,1},{1,1,1},{1,1,1}};
    float section_minimum_[5][4]{}, section_extra_draw_[4]{}, section_widths_[4]{}, column_widths_[3]{}, column_x_[3]{};
    ImVec2 section_canvas_{}, section_ghost_{};
    const char* section_names_[4]{};
    bool section_ghost_active_ = false;
    int section_resize_ = -1;
    ImVec2 resize_mouse_{}, resize_size_{};
    float sidebar_resize_width_ = 0;
    float sidebar_width_pending_ = -1;
    bool sidebar_width_current_ = false;
    ImVec2 sidebar_resize_mouse_{};
    float card_target_y_ = 0;
    float card_vertical_scale_ = 1;
    double sections_changed_at_[5]={-10,-10,-10,-10,-10};
    struct SectionPayload { int page; unsigned index; };
    static unsigned section_count(int page);
    void prepare_sections();
    void finish_section_layout();
    void save_layout();
    unsigned layout_reset_ = 0, layout_columns_ = 2, card_column_ = 0;
    float card_origin_y_ = 0, card_column_y_[3]{};
    float transport_width_ = 500, speed_width_ = 500;
    double tab_changed_at_ = -10, camera_added_at_ = -10;
    int tab_direction_ = 1;
    unsigned previous_camera_total_ = 0, animated_camera_ = ~0u, camera_row_page_ = 0;
    unsigned camera_pending_first_ = ~0u, camera_pending_page_ = 0;
    std::uint32_t camera_pending_revision_ = 0;
    double camera_pending_at_ = -10;
    bool have_camera_total_ = false, cinematic_preparing_ = false;
    std::uint32_t cinematic_revision_ = 0, cinematic_token_ = 0;
    char layout_file_[512]{};
    void layout_controls();
    void panel_handle(const char* label, bool editor = false);
    void constrain_panel();
    float motion_progress(double started, double duration = .22) const;
    float lite_timeline_height() const;
    static void* read_layout_open(ImGuiContext*, ImGuiSettingsHandler*, const char*);
    static void read_layout_line(ImGuiContext*, ImGuiSettingsHandler*, void*, const char*);
    static void write_layout(ImGuiContext*, ImGuiSettingsHandler*, ImGuiTextBuffer*);
    bool lite_mode_ = false;
    int lite_page_ = 0, lite_pending_page_ = -1;
    int lite_tick_step_ = 1;
    bool lite_campath_timeline_ = false, lite_replay_dragging_ = false;
    std::int64_t lite_replay_cursor_ = 0;
    bool lite_tick_editing_ = false, lite_fov_editing_ = false;
    char lite_tick_draft_[32]{};
    float lite_fov_draft_ = 90;
    float lite_shot_time_ = 0;
    double lite_shot_playhead_ = -1, lite_shot_duration_ = -1;
    std::int64_t lite_replay_total_seen_ = -1;
    bool lite_replay_ready_seen_ = false, lite_replay_fit_pending_ = true;
    unsigned lite_replay_events_status_seen_ = 0;
    std::uint32_t lite_shot_revision_ = 0;
    std::uint32_t lite_arrive_revision_ = 0, lite_arrive_first_ = 0;
    float lite_arrive_drafts_[kEditorCameraListCount]{};
    bool lite_arrive_editing_[kEditorCameraListCount]{};
    std::uint32_t lite_arrive_edit_revisions_[kEditorCameraListCount]{};
    std::uint32_t lite_clear_revision_ = 0;
    float lite_bank_drafts_[kEditorCameraListCount]{};
    bool lite_bank_editing_[kEditorCameraListCount]{};
    bool bank_release_pending_ = false;
    std::uint32_t bank_sent_revision_ = 0, bank_release_index_ = 0;
    float bank_sent_value_ = 0, bank_release_value_ = 0;
    double bank_anchor_time_ = 0;
    bool pause_capture_pending_value_ = false;
    std::uint64_t pause_capture_pending_until_ = 0;
    unsigned layout_card_index_ = 0;
    int replay_player_filter_ = -1;
    static void roster_label(const EditorRosterEntry& entry, char* out, std::size_t capacity);
    struct SliderRow {
        bool committed = false, active = false;
    };
    void action_button(const char* label, EditorAction action, float width = 0, double value = 0,
                       bool primary = false);
    SliderRow slider_row(const char* id, const char* label, float* value, float minimum,
                         float maximum, const char* format, float label_width = 58.0f,
                         const VisualizationPath* timeline = nullptr, bool replay_track = false);
    void section_title(const char* title, const char* detail = nullptr);
    bool begin_panel_card(const char* name);
    bool inline_controls(const char* label, const char* display = nullptr);
    void end_panel_card();
    void replay_badge(const EditorSnapshot& state);
    ImFont* panel_font = nullptr;
    ImFont* heading_font = nullptr;
    ImFont* title_font = nullptr;
    float panel_scale = 1.0f;
    bool show_path_guides = true;
    VisualizationGeometry guide_geometry;
    float timeline_x0_ = 0, timeline_x1_ = 0, timeline_y_ = 0;
    std::uint64_t timeline_drags_ = 0;
    const char* timeline_view_id_ = nullptr;
    float timeline_view_start_ = 0, timeline_view_end_ = 0;
    bool timeline_panning_ = false;
    float timeline_pan_anchor_ = 0, timeline_pan_start_ = 0, timeline_pan_end_ = 0;
};
} // namespace dolly
