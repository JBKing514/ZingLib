<template>
  <div class="dashboard-page-shell" :class="dashboardPageShellClass" @click="onPageShellClick">
          <v-card class="pa-4 mb-4">
            <div class="mb-3">
              <div class="d-flex align-center ga-2">
              <v-text-field
                v-model="homeSearchQuery"
                class="home-search-input flex-grow-1"
                density="compact"
                hide-details
                :label="t('home.search.placeholder')"
                variant="outlined"
                color="primary"
                rounded="lg"
                @keyup.enter="runHomeSearchPlaceholder"
              >
                <template #prepend-inner>
                  <v-icon
                    class="mr-2 cursor-pointer"
                    :color="imageSearchDialog ? 'primary' : 'medium-emphasis'"
                    @click="imageSearchDialog = true"
                    title="Image Search"
                  >mdi-camera-outline</v-icon>
                  <v-icon
                    v-if="showNlToggle()"
                    class="cursor-pointer"
                    :color="config.SEARCH_NL_ENABLED ? 'primary' : 'medium-emphasis'"
                    @click="toggleNlSearch"
                    title="AI Semantic Search"
                  >mdi-robot-outline</v-icon>
                </template>

                <template #append-inner>
                  <v-divider vertical class="mx-2" />
                  <v-icon
                    color="primary"
                    class="cursor-pointer"
                    @click="runHomeSearchPlaceholder"
                  >mdi-magnify</v-icon>
                </template>
              </v-text-field>

                <template v-if="!isMobile">
                  <v-btn v-if="homeTab === 'local_gallery' && !isLocalFolderMode()" color="secondary" variant="tonal" icon="mdi-sort" rounded="lg" @click="openLocalSortDialog" />
                  <v-btn v-if="isRealtimeRefreshTab(homeTab)" color="secondary" variant="tonal" icon="mdi-refresh" rounded="lg" @click="onRefreshClick" />
                  <v-btn color="primary" variant="tonal" icon="mdi-filter-variant" rounded="lg" @click="homeFiltersOpen = true" />
                </template>
              </div>

              <div v-if="isMobile" class="mobile-action-row mt-2">
                <v-btn
                  v-if="homeTab === 'local_gallery' && !isLocalFolderMode()"
                  class="mobile-action-btn"
                  color="secondary"
                  variant="tonal"
                  prepend-icon="mdi-sort"
                  rounded="lg"
                  @click="openLocalSortDialog"
                >
                  {{ t('home.local.sort.open') }}
                </v-btn>
                <v-btn
                  v-if="isRealtimeRefreshTab(homeTab)"
                  class="mobile-action-btn"
                  color="secondary"
                  variant="tonal"
                  prepend-icon="mdi-refresh"
                  rounded="lg"
                  @click="onRefreshClick"
                >
                  {{ t('common.refresh') }}
                </v-btn>
                <v-btn
                  class="mobile-action-btn"
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-filter-variant"
                  rounded="lg"
                  @click="homeFiltersOpen = true"
                >
                  {{ t('home.filter.title') }}
                </v-btn>
              </div>

            </div>

            <!-- The library / favorites / history switch lives in the sidebar rail
                 now; this row keeps only the view-mode control. -->
            <div class="d-flex align-center justify-end flex-wrap ga-2 home-tab-row" :class="{ 'home-tab-row-mobile': isMobile }">
              <v-btn-toggle
                v-model="homeViewMode"
                mandatory
                variant="outlined"
                density="compact"
                rounded="lg"
                color="primary"
                class="home-view-toggle flex-shrink-0 bg-surface"
              >
                <v-btn value="wide" :title="t('home.view.wide')">
                  <v-icon>mdi-view-grid-outline</v-icon>
                </v-btn>
                <v-btn value="compact" :title="t('home.view.compact')">
                  <v-icon>mdi-view-module-outline</v-icon>
                </v-btn>
                <v-btn value="list" :title="t('home.view.list')">
                  <v-icon>mdi-view-list-outline</v-icon>
                </v-btn>
              </v-btn-toggle>
            </div>

            <div v-if="homeTab === 'local_gallery'" class="text-caption text-medium-emphasis mt-2">
              <div class="d-flex align-center justify-space-between flex-wrap ga-2">
                <span>{{ t('home.local.folder_mode_hint') }}</span>
                <v-switch
                  :model-value="isLocalFolderMode()"
                  density="compact"
                  inset
                  hide-details
                  color="primary"
                  :label="t('home.local.folder_mode')"
                  @update:model-value="localGalleryMode = $event ? 'folder' : 'flat'"
                />
              </div>
            </div>
          </v-card>

          <v-alert v-if="activeHomeState.error" type="warning" class="mb-3">
            <div>{{ activeHomeState.error }}</div>
          </v-alert>

          <v-card v-if="isPlaceholderHomeTab()" class="pa-4 mb-3" variant="flat">
            <div class="text-subtitle-1 font-weight-bold mb-2">{{ placeholderHomeTitle() }}</div>
            <div class="text-body-2 text-medium-emphasis">{{ t('home.placeholder.pending') }}</div>
          </v-card>

          <v-card v-if="isLocalScope() && homeTab === 'local_gallery' && isLocalFolderMode()" class="pa-3 mb-3" variant="flat">
            <div class="d-flex align-center ga-2 flex-wrap">
              <v-btn size="small" variant="tonal" color="secondary" prepend-icon="mdi-arrow-up" :disabled="!localFolderPath" @click="goParentLocalFolder">Up</v-btn>
              <div class="d-flex align-center ga-1 flex-wrap text-caption text-medium-emphasis">
                <template v-for="(bc, i) in localFolderBreadcrumbs" :key="`bc-${bc.path}`">
                  <v-btn size="x-small" variant="text" @click="openLocalFolder(bc.path)">{{ bc.name }}</v-btn>
                  <span v-if="i < localFolderBreadcrumbs.length - 1">/</span>
                </template>
              </div>
            </div>
          </v-card>

          <div
            v-if="!isPlaceholderHomeTab()"
            class="home-items-zone"
          >
          <v-list
            v-if="homeViewMode === 'list'"
            class="mb-2"
            lines="two"
          >
            <v-list-item v-for="item in filteredHomeItems" :key="item.id" @click="openHomeItem(item)">
              <template #title>
                <span v-if="item.source !== 'folder'" class="cover-link-title">{{ getGalleryTitle(item) }}</span>
                <span v-else class="cover-link-title">{{ getGalleryTitle(item) }}</span>
              </template>
              <template #subtitle>
                <div v-if="itemRatingValue(item) !== null" class="d-flex align-center ga-1 mt-1">
                  <v-rating :model-value="itemRatingValue(item)" readonly half-increments density="compact" size="x-small" color="amber" empty-icon="mdi-star-outline" full-icon="mdi-star" half-icon="mdi-star-half-full" />
                  <span class="text-caption text-medium-emphasis">{{ Number(itemRatingValue(item)).toFixed(1) }}</span>
                </div>
                <div class="text-caption text-medium-emphasis text-truncate">{{ itemSubtitle(item) }}</div>
              </template>
              <template #prepend>
                <div class="list-cover" @contextmenu.prevent>
                  <template v-if="item.source === 'folder'">
                    <v-icon size="20" color="amber">mdi-folder-outline</v-icon>
                  </template>
                  <template v-else>
                    <img v-if="item.thumb_url" :src="item.thumb_url" alt="cover" class="cover-img list-cover-img" loading="lazy" draggable="false" @dragstart.prevent @load="onImageLoaded(item)" @error="onImageError(item)" />
                    <v-icon v-else size="18">mdi-image-outline</v-icon>
                  </template>
                </div>
              </template>
              <template #append>
                <v-btn
                  v-if="item.source === 'works' && item.arcid"
                  icon="mdi-play"
                  size="small"
                  variant="tonal"
                  @click.stop="startReader(item)"
                />
              </template>
            </v-list-item>
          </v-list>

          <v-row v-else>
              <v-col
               v-for="(item, itemIndex) in filteredHomeItems"
                :key="item.id"
                cols="12"
                :sm="homeViewMode === 'wide' ? 6 : 4"
                :md="homeViewMode === 'wide' ? 4 : 3"
                :lg="homeViewMode === 'wide' ? 3 : 2"
              >
              <v-card
                class="home-card"
                :class="{ compact: homeViewMode === 'compact' }"
                variant="flat"
                @touchstart.passive="onCardTouchStart(item, itemIndex, $event)"
                @touchmove.passive="onCardTouchMove($event)"
                @touchend.passive="onCardTouchEnd($event)"
                @touchcancel.passive="onCardTouchCancel"
                @contextmenu.prevent
                @mouseenter="onCardMouseEnter(item, $event)"
                @mousemove="onCardMouseMove(item, $event)"
                @mouseleave="onCardMouseLeave"
                @click="onCardClick(item)"
              >
                <div class="cover-anchor">
                  <div class="cover-ph">
                    <template v-if="item.source === 'folder'">
                      <v-icon size="40" color="amber">mdi-folder-multiple-image</v-icon>
                    </template>
                    <template v-else>
                      <img v-if="item.thumb_url" :src="item.thumb_url" alt="cover" class="cover-img" loading="lazy" draggable="false" @dragstart.prevent @load="onImageLoaded(item)" @error="onImageError(item)" />
                      <v-icon v-else size="30">mdi-image-outline</v-icon>
                    </template>
                    <div class="cover-guard" @contextmenu.prevent />
                      <div v-if="categoryLabel(item)" class="cat-badge" :style="categoryBadgeStyle(item)">{{ categoryLabel(item) }}</div>
                    </div>
                  <div v-if="homeViewMode === 'compact'" class="cover-title-overlay">{{ getGalleryTitle(item) }}</div>
                </div>
                <div v-if="homeViewMode !== 'compact'" class="pa-2">
                  <div v-if="item.source !== 'folder'" class="text-body-2 font-weight-medium text-truncate cover-link-title d-block">{{ getGalleryTitle(item) }}</div>
                  <div v-else class="text-body-2 font-weight-medium text-truncate cover-link-title d-block">{{ getGalleryTitle(item) }}</div>
                  <div class="text-caption text-medium-emphasis text-truncate">{{ itemSubtitle(item) }}</div>
                  <div v-if="itemRatingValue(item) !== null" class="d-flex align-center ga-1 mt-1">
                    <v-rating :model-value="itemRatingValue(item)" readonly half-increments density="compact" size="x-small" color="amber" empty-icon="mdi-star-outline" full-icon="mdi-star" half-icon="mdi-star-half-full" />
                    <span class="text-caption text-medium-emphasis">{{ Number(itemRatingValue(item)).toFixed(1) }}</span>
                  </div>
                </div>
              </v-card>
            </v-col>
          </v-row>

          <div ref="homeSentinel" class="home-sentinel" />
          <!-- The bottom affordance is the one place the two presentation modes
               must not overlap: an appending feed offers "load more", a paged
               feed offers a page bar. Exactly one of them is ever rendered. -->
          <div v-if="!feedPaged" class="d-flex justify-center py-2">
            <v-btn
              v-if="!activeHomeState.loading"
              color="primary"
              variant="tonal"
              @click="onManualLoadMoreClick"
            >{{ t('common.load_more') }}</v-btn>
          </div>
          <FeedPager
            v-else
            :visible="!isPlaceholderHomeTab()"
            :page="feedPage"
            :page-size="feedPageSize"
            :can-prev="feedCanPrev"
            :can-next="feedCanNext"
            :max-page="feedMaxJump"
            :loading="activeHomeState.loading"
            :t="t"
            @prev="onPagerPrev"
            @next="onPagerNext"
            @jump="onPagerJump"
          />
          <!-- Pull-to-page never replaces the page bar: it is an extra gesture on
               top of it, and it is only offered while there is a next page. -->
          <FeedPullToPage
            v-if="feedPaged && feedPullToPage && feedCanNext"
            :next-page="feedPage + 1"
            :busy="activeHomeState.loading"
            :t="t"
            @advance="onPagerNext"
          />
          <div v-if="activeHomeState.loading" class="text-center py-3"><v-progress-circular indeterminate color="primary" size="24" /></div>
          <div v-else-if="!filteredHomeItems.length" class="text-center text-medium-emphasis py-8">
            <template v-if="libraryEmptyWithoutFilters">
              <div class="text-body-1 mb-1">{{ t('home.empty_library') }}</div>
              <div class="text-caption mb-3">{{ t('home.empty_library_hint') }}</div>
              <v-btn color="primary" variant="tonal" prepend-icon="mdi-upload" @click="goToUploader">
                {{ t('home.empty_library_action') }}
              </v-btn>
            </template>
            <template v-else>{{ t('home.empty') }}</template>
          </div>
          </div>

          <div v-if="longPressPickerOpen" class="longpress-picker-backdrop" />

          <div
            v-if="longPressPickerOpen && longPressPickerItems.length"
            ref="longPressPickerHost"
            class="longpress-picker-host"
            :style="longPressPickerStyle"
            @touchstart.stop
            @touchmove.stop.prevent="onCardTouchMove($event)"
            @touchend.stop.prevent="onCardTouchEnd($event)"
            @touchcancel.stop.prevent="onCardTouchCancel"
            @contextmenu.prevent
          >
            <v-card class="longpress-picker-card" :style="longPressCardStyle" variant="flat">
              <div class="longpress-picker-track">
                <div
                  v-for="(lpItem, lpIndex) in longPressPickerItems"
                  :key="`lp-${previewItemKey(lpItem) || lpItem.id || lpIndex}`"
                  class="longpress-picker-item"
                  :class="{ active: lpIndex === longPressPickerIndex, inactive: lpIndex !== longPressPickerIndex }"
                >
                  <div class="longpress-picker-thumb-wrap">
                    <img v-if="lpItem.thumb_url" :src="lpItem.thumb_url" alt="cover" class="longpress-picker-thumb" draggable="false" @dragstart.prevent @contextmenu.prevent />
                    <div v-else class="longpress-picker-thumb-fallback"><v-icon size="18">mdi-image-outline</v-icon></div>
                    <div v-if="lpIndex !== longPressPickerIndex" class="longpress-picker-mask" />
                  </div>
                  <div class="longpress-picker-title">{{ getGalleryTitle(lpItem) }}</div>
                </div>
              </div>
            </v-card>
          </div>

          <div
            v-if="effectivePreviewUiMode === 'desktop' && showDesktopHoverPreview && desktopHoverPreviewItem"
            :key="desktopHoverPreviewKey"
            class="desktop-hover-ghost"
            :style="{ left: `${desktopHoverPreviewX}px`, top: `${desktopHoverPreviewY}px` }"
            @mouseenter="clearDesktopHoverTimer"
            @mouseleave="onGhostPreviewLeave"
            @contextmenu.prevent
          >
            <v-card elevation="12" class="rounded-lg overflow-hidden border bg-surface" width="480">
              <PreviewCard
                :item="desktopHoverPreviewItem"
                :is-mobile="false"
                :hide-start-button="false"
                :t="t"
                :get-gallery-title="getGalleryTitle"
                :item-hover-tags="itemHoverTags"
                :is-tag-filter-active="isTagFilterActive"
                :is-favorited="isFavorited(desktopHoverPreviewItem)"
                :item-rating-value="itemRatingValue"
                :allow-delete-local="isLocalScope()"
                @start-reader="startReader"
                @start-reader-at-page="startReaderAtPage"
                @favorite-toggle="requestFavoriteToggle"
                @delete-local="requestLocalDelete"
                @toggle-tag="toggleTagFilter"
              @apply-tag-filter="onPreviewApplyTagFilter"
                @set-rating="setItemRating"
                @hydrated="onPreviewHydrated"
                @image-error="onImageError"
                @quick-add-tag="openQuickTagDialog"
              />
            </v-card>
          </div>

          <transition :name="mobilePreviewTransitionName">
            <div
              v-if="showMobilePreview && resolvedMobilePreviewItem"
              class="mobile-preview-fullscreen"
              :class="mobilePreviewPaneClass"
              @touchstart.stop="onMobilePreviewTouchStart"
              @touchmove.stop="onMobilePreviewTouchMove"
              @touchend.stop="onMobilePreviewTouchEnd"
              @touchcancel.stop="onMobilePreviewTouchCancel"
            >
              <div class="mobile-preview-toolbar">
                <div class="d-flex ga-2 align-center">
                  <v-btn size="small" icon="mdi-arrow-left" color="primary" variant="tonal" @click="closeMobilePreview" />
                  <v-btn size="small" icon="mdi-home-variant-outline" color="secondary" variant="tonal" @click="closeAllOverlayPanels" />
                </div>
                <div class="text-caption text-medium-emphasis">{{ t('home.search.quick_title') }}</div>
              </div>
              <div class="mobile-preview-body">
                <PreviewCard
                  :item="resolvedMobilePreviewItem"
                  :is-mobile="true"
                  :defer-thumb-load-ms="isTabletDrawerPreview ? 240 : 0"
                  :hide-start-button="false"
                  :t="t"
                  :get-gallery-title="getGalleryTitle"
                  :item-hover-tags="itemHoverTags"
                  :is-tag-filter-active="isTagFilterActive"
                  :is-favorited="isFavorited(resolvedMobilePreviewItem)"
                  :item-rating-value="itemRatingValue"
                  :allow-delete-local="isLocalScope()"
                  @start-reader="startReader"
                  @start-reader-at-page="startReaderAtPage"
                  @favorite-toggle="requestFavoriteToggle"
                  @delete-local="requestLocalDelete"
                  @toggle-tag="toggleTagFilter"
                  @apply-tag-filter="onPreviewApplyTagFilter"
                  @set-rating="setItemRating"
                  @hydrated="onPreviewHydrated"
                  @image-error="onImageError"
                  @quick-add-tag="openQuickTagDialog"
                />
              </div>
            </div>
          </transition>

          <v-dialog v-model="quickTagDialogOpen" max-width="560" :persistent="quickTagSaving" :z-index="3200">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-2 mb-2">{{ t('home.preview.quick_add_tag') }}</div>
              <!-- Left: namespace. Right: value + suggestions. The namespace is a
                   separate control, so the typed text is the tag value itself. -->
              <div class="quick-tag-composer">
                <v-select
                  v-model="quickTagNs"
                  :items="quickTagNamespaceOptions()"
                  density="compact"
                  variant="outlined"
                  hide-details
                  :label="t('tools.metadata_editor.tag_namespace')"
                  class="quick-tag-ns"
                  @update:model-value="onQuickTagNamespaceChange"
                />
                <v-text-field
                  v-model="quickTagSearch"
                  density="compact"
                  variant="outlined"
                  hide-details
                  clearable
                  :label="t('tools.metadata_editor.tag_input')"
                  class="quick-tag-input"
                  @keydown.enter.prevent="commitQuickTag"
                  @update:model-value="onQuickTagSearch"
                />
                <v-btn class="quick-tag-add" size="small" variant="tonal" :disabled="!String(quickTagSearch || '').trim()" @click="commitQuickTag">{{ t('tools.metadata_editor.tag_add') }}</v-btn>
              </div>
              <div v-if="quickTagSuggest.length" class="d-flex flex-wrap ga-1 mt-2">
                <v-chip
                  v-for="label in quickTagSuggest"
                  :key="`quick-sug-${label}`"
                  size="x-small"
                  variant="text"
                  class="tag-suggest-chip"
                  @mousedown.prevent
                  @click.stop="pickQuickTagSuggestion(label)"
                >{{ label }}</v-chip>
              </div>
              <div v-else-if="String(quickTagSearch || '').trim()" class="text-caption text-medium-emphasis mt-2">
                {{ t('tools.metadata_editor.tag_no_candidate') }}
              </div>
              <div class="d-flex flex-wrap ga-1 mt-2 quick-tag-staged">
                <v-chip
                  v-for="tag in quickTagInput"
                  :key="`quick-tmp-${tag}`"
                  size="small"
                  variant="tonal"
                  closable
                  @click:close="removeQuickTag(tag)"
                >{{ displayQuickTag(tag) }}</v-chip>
                <span v-if="!quickTagInput.length" class="text-caption text-medium-emphasis">{{ t('home.preview.quick_add_tag_hint') }}</span>
              </div>
              <div class="d-flex justify-end ga-2 mt-2">
                <v-btn variant="text" :disabled="quickTagSaving" @click="closeQuickTagDialog">{{ t('home.favorite.dialog.cancel') }}</v-btn>
                <v-btn color="primary" :loading="quickTagSaving" @click="applyQuickTagDialog">{{ t('home.favorite.dialog.confirm') }}</v-btn>
              </div>
            </v-card>
          </v-dialog>

          <v-dialog v-model="deleteDialogOpen" max-width="560" :z-index="3200">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.local.delete.title') }}</div>
              <div class="text-body-2 mb-2">{{ t('home.local.delete.hint') }}</div>
              <v-switch v-model="deleteDialogDeleteFiles" color="error" inset hide-details :label="t('home.local.delete.files')" class="mb-2" />
              <v-switch v-model="deleteDialogDeleteDb" color="warning" inset hide-details :label="t('home.local.delete.db')" class="mb-2" />
              <v-switch v-model="deleteDialogDeleteReadEvents" color="error" inset hide-details :label="t('home.local.delete.events')" class="mb-2" />
              <v-alert
                v-if="deleteDialogDeleteReadEvents"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-2"
              >{{ t('home.local.delete.events_warn') }}</v-alert>
              <v-checkbox
                v-if="deleteDialogDeleteReadEvents"
                v-model="deleteDialogDangerConfirmed"
                density="compact"
                hide-details
                :label="t('home.local.delete.events_confirm')"
              />
              <div class="d-flex justify-end ga-2 mt-3">
                <v-btn variant="text" @click="deleteDialogOpen = false">{{ t('home.image_upload.cancel') }}</v-btn>
                <v-btn color="error" variant="flat" :disabled="deleteDialogDeleteReadEvents && !deleteDialogDangerConfirmed" @click="applyLocalDelete">{{ t('common.delete') }}</v-btn>
              </div>
            </v-card>
          </v-dialog>

          <v-dialog v-model="imageSearchDialog" max-width="560">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.image_upload.title') }}</div>
              <div
                class="upload-dropzone"
                :class="{ active: imageDropActive }"
                @dragover.prevent="imageDropActive = true"
                @dragleave.prevent="imageDropActive = false"
                @drop.prevent="onImageDrop"
                @click="triggerImagePicker"
              >
                <div class="text-body-2">{{ selectedImageFile ? selectedImageFile.name : t('home.image_upload.hint') }}</div>
                <div class="text-caption text-medium-emphasis">{{ t('home.image_upload.subhint') }}</div>
              </div>
              <input ref="imageFileInputRef" type="file" accept="image/*" class="d-none" @change="onImagePickChange" />
              <v-text-field
                v-model="imageSearchQuery"
                class="mt-3"
                density="compact"
                variant="outlined"
                :label="t('home.search.extra_text')"
                :hint="t('home.search.extra_text_hint')"
                persistent-hint
                @keyup.enter="runImageUploadSearch"
              />
              <div class="d-flex ga-2 mt-3 justify-end">
                <v-btn variant="text" @click="imageSearchDialog = false">{{ t('home.image_upload.cancel') }}</v-btn>
                <v-btn color="primary" :disabled="!selectedImageFile" @click="runImageUploadSearch">{{ t('home.image_upload.search') }}</v-btn>
              </div>
            </v-card>
          </v-dialog>

          <v-dialog v-model="homeFiltersOpen" max-width="680">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.filter.title') }}</div>
              <div class="text-caption text-medium-emphasis mb-3">{{ t('home.filter.hint') }}</div>

              <div class="d-flex align-center justify-space-between mb-2">
                <div class="text-body-2">{{ t('home.filter.categories') }}</div>
                <div class="d-flex ga-2">
                  <v-btn size="small" variant="text" color="primary" @click="selectAllHomeFilterCategories">{{ t('home.filter.select_all') }}</v-btn>
                  <v-btn size="small" variant="text" color="medium-emphasis" @click="clearAllHomeFilterCategories">{{ t('home.filter.select_none') }}</v-btn>
                </div>
              </div>

              <div
                class="mb-4"
                :class="{ 'mobile-category-grid': isMobile }"
                :style="{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2, max-content)' : 'repeat(5, 1fr)', gap: isMobile ? '6px' : '8px' }"
              >
                <v-btn
                  v-for="cat in pinnedHomeFilterCategoryDefs"
                  :key="`f-${cat.key}`"
                  class="category-btn text-caption font-weight-bold"
                  :class="{ 'mobile-category-btn': isMobile }"
                  :height="isMobile ? 40 : 32"
                  rounded="lg"
                  variant="flat"
                  :style="homeFilterCategoryStyle(cat.key, cat.color)"
                  @click="toggleHomeFilterCategory(cat.key)"
                >
                  <span class="text-truncate">{{ categoryLabelFor(cat) }}</span>
                </v-btn>
              </div>

              <v-autocomplete
                v-model="homeFilters.tags"
                v-model:search="filterTagInput"
                :items="filterTagSuggestions"
                multiple
                chips
                closable-chips
                clearable
                variant="outlined"
                density="compact"
                color="primary"
                :label="t('home.filter.tags')"
                :hint="t('home.filter.tags_hint')"
                persistent-hint
                class="mb-2"
              />

              <div class="mt-1 mb-2">
                <div class="d-flex align-center justify-space-between mb-1">
                  <div class="text-body-2">{{ t('home.filter.min_rating') }}</div>
                  <div class="text-caption text-medium-emphasis">{{ Number(homeFilters.minRating || 0).toFixed(1) }}★</div>
                </div>
                <v-slider
                  v-model="homeFilters.minRating"
                  :min="0"
                  :max="5"
                  :step="0.5"
                  color="amber"
                  thumb-label
                  density="compact"
                  hide-details
                />
              </div>


              <div class="d-flex justify-space-between mt-2">
                <v-btn size="small" :color="config.SEARCH_TAG_SMART_ENABLED ? 'primary' : undefined" :variant="config.SEARCH_TAG_SMART_ENABLED ? 'tonal' : 'outlined'" @click="config.SEARCH_TAG_SMART_ENABLED = !config.SEARCH_TAG_SMART_ENABLED">
                  {{ t('home.filter.smart') }}
                </v-btn>
              </div>

              <div class="d-flex justify-space-between align-center mt-3">
                <v-btn variant="text" @click="clearHomeFilters">{{ t('home.filter.clear') }}</v-btn>
                <div class="d-flex ga-2">
                  <v-btn variant="text" @click="cancelHomeFilters">{{ t('home.filter.cancel') }}</v-btn>
                  <v-btn color="primary" variant="flat" @click="applyHomeFilters">{{ t('home.filter.apply') }}</v-btn>
                </div>
              </div>
            </v-card>
          </v-dialog>

          <v-dialog v-model="quickSearchOpen" max-width="560">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.search.quick_title') }}</div>
              <v-text-field
                v-model="homeSearchQuery"
                density="compact"
                hide-details
                :label="t('home.search.placeholder')"
                variant="outlined"
                @keyup.enter="runQuickSearch"
              />
              <div class="d-flex ga-2 mt-3 justify-end">
                <v-btn variant="text" @click="quickSearchOpen = false">{{ t('home.image_upload.cancel') }}</v-btn>
                <v-btn color="primary" variant="tonal" @click="runQuickSearch">{{ t('home.search.go') }}</v-btn>
                <v-btn color="secondary" variant="tonal" @click="quickImageSearch">{{ t('home.image_upload.title') }}</v-btn>
                <v-btn color="primary" variant="text" @click="openQuickFilters">{{ t('home.filter.title') }}</v-btn>
              </div>
            </v-card>
          </v-dialog>

          <TagExploreOverlay
            v-model="tagExploreOpen"
            :seed-tag="tagExploreSeedTag"
            :is-mobile="isMobile"
            :preview-ui-mode="effectivePreviewUiMode"
            :preview-drawer-side="previewDrawerSide"
            :desktop-anchor-x="desktopHoverPreviewX"
            :desktop-anchor-y="desktopHoverPreviewY"
            :category-defs="localCategoryDefs"
            :config="config"
            :allow-delete-local="isLocalScope()"
            :t="t"
            :get-gallery-title="getGalleryTitle"
            :item-subtitle="itemSubtitle"
            :item-hover-tags="itemHoverTags"
            :is-favorited="isFavorited"
            :item-rating-value="itemRatingValue"
            :category-label="categoryLabel"
            :category-badge-style="categoryBadgeStyle"
            @close-all="closeAllOverlayPanels"
            @start-reader="startReader"
            @start-reader-at-page="startReaderAtPage"
            @favorite-toggle="requestFavoriteToggle"
            @delete-local="requestLocalDelete"
            @set-rating="setItemRating"
            @hydrated="onPreviewHydrated"
            @image-error="onImageError"
            @quick-add-tag="openQuickTagDialog"
          />

          <v-dialog v-model="localSortOpen" max-width="520">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('home.local.sort.title') }}</div>
              <v-radio-group v-model="localSortBy" color="primary" hide-details>
                <v-radio :label="t('home.local.sort.xp')" value="xp" />
                <v-radio :label="t('home.local.sort.alphabetical')" value="title" />
                <v-radio :label="t('home.local.sort.date_added')" value="date_added" />
              </v-radio-group>
              <v-switch
                v-model="localSortAsc"
                color="primary"
                inset
                hide-details
                class="mt-2"
                :label="localSortAsc ? t('home.local.sort.asc') : t('home.local.sort.desc')"
              />
              <div class="d-flex justify-end ga-2 mt-4">
                <v-btn variant="text" @click="localSortOpen = false">{{ t('home.image_upload.cancel') }}</v-btn>
                <v-btn color="primary" @click="applyLocalSort">{{ t('home.filter.apply') }}</v-btn>
              </div>
            </v-card>
          </v-dialog>
  </div>
</template>

<script>
import { useDashboardStore } from "../stores/dashboardStore";
import { useLayoutStore } from "../stores/layoutStore";
import { useReaderQueueStore } from "../stores/readerQueueStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useToastStore } from "../stores/useToastStore";
import PreviewCard from "../components/dashboard/PreviewCard.vue";
import TagExploreOverlay from "../components/dashboard/TagExploreOverlay.vue";
import FeedPager from "../components/dashboard/FeedPager.vue";
import FeedPullToPage from "../components/dashboard/FeedPullToPage.vue";
import { clearFeedScroll, readFeedScroll, writeFeedScroll } from "../utils/feedScrollMemory";
import {
  batchUpdateLocalMeta,
  deleteLocalGallery,
  getHomeTagSuggest,
} from "../api";
import {
  BUILTIN_NAMESPACE_DEFS,
  getNamespaceDisplayLabel,
  normalizeNamespaceKey,
  normalizeUserTagInput,
  stripUserTagMarker,
  tagSuggestLabels,
} from "../utils/tagNamespaces";
import { getCategoryLabel } from "../utils/categoryPresets";

// What a tap on the page is allowed to mean instead of "put the tablet preview
// away". Galleries stay galleries, controls stay controls, and a panel that
// captures its own clicks keeps them; everything else in the shell is the blank
// space between them.
const SHELL_CLICK_KEEPS_PREVIEW = [
  ".home-card",
  ".v-btn",
  ".v-btn-toggle",
  ".v-chip",
  ".v-list-item",
  ".v-field",
  ".v-selection-control",
  ".v-slider",
  ".v-rating",
  ".v-pagination",
  ".v-overlay-container",
  ".mobile-preview-fullscreen",
  ".longpress-picker-host",
  ".longpress-picker-backdrop",
  ".tag-explore-host",
  "a",
  "button",
  "input",
  "select",
  "textarea",
  "label",
  '[role="button"]',
].join(", ");

export default {
  name: "DashboardScopePage",
  props: {
    scope: { type: String, default: "local" },
  },
  components: { PreviewCard, TagExploreOverlay, FeedPager, FeedPullToPage },
  data() {
    return {
      _autoRefreshTimer: null,
      _syncingRouteTab: false,
      deleteDialogOpen: false,
      deleteDialogItem: null,
      deleteDialogDeleteFiles: false,
      deleteDialogDeleteDb: false,
      deleteDialogDeleteReadEvents: false,
      deleteDialogDangerConfirmed: false,
      showDesktopHoverPreview: false,
      desktopHoverPreviewItem: null,
      desktopHoverPreviewX: 0,
      desktopHoverPreviewY: 0,
      desktopHoverPreviewKey: 0,
      _hoverLeaveTimer: null,
      _hoverOpenTimer: null,
      _hoverPendingItem: null,
      _hoverPendingPos: null,
      _hoverOpenDelayMs: 500,
      _hoverInsidePreview: false,
      _hoverTargetRect: null,
      quickTagDialogOpen: false,
      quickTagItem: null,
      // Two-part composer, mirroring the metadata editor: the namespace comes
      // from a dropdown and the text box only ever holds a tag value.
      quickTagNs: "other",
      quickTagSearch: "",
      quickTagInput: [],
      quickTagSuggest: [],
      quickTagSaving: false,
      quickTagSuggestSeq: 0,
      tempMobileItem: null,
      isTouchInteraction: false,
      viewportWidth: 0,
      _leftPreviewPrevRail: null,
      _mobilePreviewSwipeTracking: false,
      _mobilePreviewSwipeStartX: 0,
      _mobilePreviewSwipeStartY: 0,
      _mobilePreviewSwipeLastX: 0,
      _mobilePreviewSwipeLastY: 0,
      tagExploreOpen: false,
      tagExploreSeedTag: "",
      longPressPickerOpen: false,
      longPressPickerItems: [],
      longPressPickerIndex: 0,
      _longPressTimer: null,
      _longPressActive: false,
      _longPressStartX: 0,
      _longPressStartY: 0,
      _longPressMoveX: 0,
      _longPressBaseIndex: 0,
      _longPressSuppressClickUntil: 0,
      _longPressAnchorY: 0,
      // The offsets themselves live in feedScrollMemory (module scope, so they
      // outlive a remount); these two only guard the restore in flight.
      _feedRestoreUntil: 0,
      _feedRestoreTarget: 0,
      // Set when the presentation is switched from another route: the feed that is
      // waiting for us was rebuilt, so it wants the top rather than an old offset.
      _feedPendingTop: false,
      _longPressBodyPrevOverflow: "",
      _longPressBodyPrevTouchAction: "",
      _longPressAbortOpen: false,
    };
  },
  computed: {
    // One offset per feed, not one per component: local library, favorites and
    // history each keep their own place. Folder mode is part of the identity
    // because entering a folder is a different feed with different rows.
    feedScrollKey() {
      return this._feedScrollKeyFor(this.homeTab);
    },
    effectivePreviewUiMode() {
      const raw = String(this.config?.REC_PREVIEW_UI_MODE || "auto").trim().toLowerCase();
      const forced = ["auto", "phone", "tablet", "desktop"].includes(raw) ? raw : "auto";
      const w = Number(this.viewportWidth || (typeof window !== "undefined" ? window.innerWidth : 0) || 0);
      if (w > 0 && w < 700) {
        return "phone";
      }
      if (forced !== "auto") {
        return forced;
      }
      if (this.isTouchInteraction) {
        return w >= 768 ? "tablet" : "phone";
      }
      return "desktop";
    },
    useRoutePreview() {
      return this.effectivePreviewUiMode !== "desktop";
    },
    isTabletDrawerPreview() {
      return this.effectivePreviewUiMode === "tablet" && Number(this.viewportWidth || 0) >= 768;
    },
    previewDrawerSide() {
      const side = String(this.config?.REC_PREVIEW_DRAWER_SIDE || "right").trim().toLowerCase();
      return side === "left" ? "left" : "right";
    },
    mobilePreviewPaneClass() {
      return {
        "tablet-preview-drawer": this.isTabletDrawerPreview,
        "drawer-left": this.isTabletDrawerPreview && this.previewDrawerSide === "left",
        "drawer-right": this.isTabletDrawerPreview && this.previewDrawerSide !== "left",
      };
    },
    mobilePreviewTransitionName() {
      return this.isTabletDrawerPreview ? "preview-slide-side" : "preview-slide-up";
    },
    dashboardPageShellClass() {
      return {
        "tablet-preview-open-right": this.isTabletDrawerPreview && this.showMobilePreview && this.previewDrawerSide !== "left",
      };
    },
    longPressPickerStyle() {
      const y = Number(this._longPressAnchorY || 0);
      if (!Number.isFinite(y) || y <= 0) return {};
      const vh = Number(this.viewportWidth || (typeof window !== "undefined" ? window.innerWidth : 0) || 0) > 0
        ? (typeof window !== "undefined" ? window.innerHeight : 0)
        : 0;
      const cardH = 210;
      const top = Math.max(16, Math.min(Math.max(16, vh - cardH - 16), Math.round(y - cardH * 0.55)));
      return { top: `${top}px` };
    },
    longPressCardStyle() {
      const n = Math.max(1, Number((this.longPressPickerItems || []).length || 1));
      const item = 102;
      const gap = 5;
      const sidePad = 16;
      const target = n * item + (n - 1) * gap + sidePad;
      return { width: `min(92vw, ${Math.round(target)}px)` };
    },
    showMobilePreview() {
      return this.useRoutePreview && !!String(this.$route?.query?.pv || "").trim();
    },
    resolvedMobilePreviewItem() {
      const pv = String(this.$route?.query?.pv || "").trim();
      if (!pv) return null;
      const tempKey = this.previewItemKey(this.tempMobileItem);
      if (tempKey && tempKey === pv && this.tempMobileItem) {
        return this.tempMobileItem;
      }
      const hit = this.findPreviewItemByKey(pv)
        || this.findPreviewItemByKey(pv, Array.isArray(this.activeHomeState?.items) ? this.activeHomeState.items : []);
      return hit || this.tempMobileItem || null;
    },
  },
  setup() {
    return useDashboardStore();
  },
  mounted() {
    this.config.REC_SHOW_PAGE_COUNT = true;
    this.refreshTouchInteraction();
    if (typeof this.updateViewportFlags === "function") {
      this.updateViewportFlags();
    }
    this.applyRouteScopedTab();
    this.ensureScopeTab();
    this.applyReaderOriginRestore();
    this.syncMobilePreviewFromRoute();
    this.ensureLeftTabletPreviewRailMode();
    this.$nextTick(() => {
      if (typeof this.bindHomeInfiniteScroll === "function") {
        this.bindHomeInfiniteScroll();
      }
      this._restoreFeedScroll(this.homeTab);
    });
    this._autoRefreshTimer = setInterval(() => {
      if (!this.isRealtimeRefreshTab(this.homeTab)) return;
      if (!this.isFeedStale(this.homeTab, 5 * 60 * 1000)) return;
      this.refreshCurrentHomeFeed({ force: false }).catch(() => null);
    }, 30000);
    window.addEventListener("scroll", this.onFeedScroll, { passive: true });
    window.addEventListener("scroll", this.closeDesktopHoverPreview, { passive: true });
    window.addEventListener("resize", this.closeDesktopHoverPreview, { passive: true });
    window.addEventListener("resize", this.onViewportResize, { passive: true });
    window.addEventListener("touchstart", this.markTouchInteraction, { passive: true });
    window.addEventListener("pointerdown", this.onPointerDownCapture, { passive: true });
  },
  activated() {
    // Coming back from the toolbox or the settings page. `<KeepAlive>` kept the
    // feed rows, but the app shares one window scroller, so the detour to a
    // shorter page clamped the offset to zero -- put the user back.
    if (this._feedPendingTop) {
      // The presentation was switched while we were away, so the store rebuilt the
      // row set: an offset from the old rows points into content that is gone.
      this._feedPendingTop = false;
      this._scrollFeedToTop();
    } else {
      this._restoreFeedScroll(this.homeTab);
    }
    // The mode switch also disconnects the scroll observer. Without rebinding here
    // an infinite feed would never append again, and a paged one would stay empty
    // whenever the background rebuild lost the race.
    this.$nextTick(() => {
      if (typeof this.bindHomeInfiniteScroll === "function") this.bindHomeInfiniteScroll();
    });
  },
  deactivated() {
    // Leaving. This is the only reliable "last chance" write: the destination
    // page mounts before the browser reflows, so by the time a route guard could
    // read scrollY it is already the new page's.
    this._saveFeedScroll();
  },
  beforeUnmount() {
    this.closeLongPressPicker(true);
    this._saveFeedScroll();
    if (this._autoRefreshTimer) {
      clearInterval(this._autoRefreshTimer);
      this._autoRefreshTimer = null;
    }
    window.removeEventListener("scroll", this.onFeedScroll);
    window.removeEventListener("scroll", this.closeDesktopHoverPreview);
    window.removeEventListener("resize", this.closeDesktopHoverPreview);
    window.removeEventListener("resize", this.onViewportResize);
    window.removeEventListener("touchstart", this.markTouchInteraction);
    window.removeEventListener("pointerdown", this.onPointerDownCapture);
    this.closeDesktopHoverPreview();
    this.restoreLeftTabletPreviewRailMode(true);
  },
  watch: {
    homeTab(next, prev) {
      // Hand the tab we are leaving its place back before anything re-renders.
      this._saveFeedScroll(prev);
      this.ensureScopeTab();
      this.syncRouteScopedTab();
      const state = this.activeHomeState || {};
      if (!Array.isArray(state.items) || !state.items.length) {
        if (typeof this.resetHomeFeed === "function") {
          this.resetHomeFeed().catch(() => null);
        }
      } else if (this.isRealtimeRefreshTab(next) && this.isFeedStale(next, 5 * 60 * 1000)) {
        this.refreshCurrentHomeFeed({ force: false }).catch(() => null);
      }
      this.$nextTick(() => {
        if (typeof this.bindHomeInfiniteScroll === "function") {
          this.bindHomeInfiniteScroll();
        }
        // Each feed carries its own offset, so switching back lands where the
        // user left -- the same guarantee as returning from another route.
        this._restoreFeedScroll(next);
      });
    },
    feedPaged() {
      // Switching presentation replaces the whole row set: an appended pile is
      // not a page, and a page is not something scrolling may append onto. The
      // remembered offsets point into content that no longer exists, so drop
      // them and start the new mode at the top.
      clearFeedScroll();
      this._feedRestoreUntil = 0;
      this._feedRestoreTarget = 0;
      if (String(this.$route?.name || "") === "dashboard") {
        this._scrollFeedToTop();
      } else {
        // The switch happens over in the settings tab. Scrolling *that* page to the
        // top would be rude; remember to do it on the way back instead.
        this._feedPendingTop = true;
      }
    },
    filterTagInput() {
      if (typeof this.loadTagSuggestions === "function") {
        this.loadTagSuggestions().catch(() => null);
      }
    },
    localGalleryMode(next) {
      if (!this.isLocalScope() || String(this.homeTab || "") !== "local_gallery") return;
      if (String(next || "flat") === "flat") {
        this.localFolderPath = "";
      }
      this.resetHomeFeed().catch(() => null);
    },
    "$route.query": {
      deep: true,
      handler() {
        if (this._syncingRouteTab) return;
        this.applyRouteScopedTab();
        this.syncMobilePreviewFromRoute();
      },
    },
    quickTagDialogOpen(val) {
      if (!val) this.quickTagSuggestSeq += 1;
      if (!val && this.showDesktopHoverPreview) {
        this.showDesktopHoverPreview = false;
        this.desktopHoverPreviewItem = null;
      }
    },
    showMobilePreview(next) {
      if (next) {
        this.ensureLeftTabletPreviewRailMode();
      } else {
        this.restoreLeftTabletPreviewRailMode(true);
      }
    },
    previewDrawerSide() {
      this.ensureLeftTabletPreviewRailMode();
      this.restoreLeftTabletPreviewRailMode();
    },
    effectivePreviewUiMode() {
      this.closeDesktopHoverPreview();
      this.syncMobilePreviewFromRoute();
      this.ensureLeftTabletPreviewRailMode();
      this.restoreLeftTabletPreviewRailMode();
    },
  },
  methods: {
    // Uploading galleries lives in the toolbox file manager, not on the feed, so
    // the empty-library state has to hand the user the path to it -- otherwise
    // "your library is empty" is a dead end for someone who skipped the setup
    // wizard's upload step.
    goToUploader() {
      this.$router.push({ path: "/tools", query: { tab: "file_manager" } }).catch(() => null);
    },
    onCardClick(item) {
      if (Date.now() < Number(this._longPressSuppressClickUntil || 0)) return;
      this.openHomeItem(item);
    },
    // In the tablet presentation the preview is a side pane and the feed behind
    // it stays live. A tap on a gallery belongs to that gallery, a tap on a
    // control belongs to that control, and a tap on the space between them means
    // "put the pane away" -- until now only the card's own back arrow could.
    onPageShellClick(event) {
      if (!this.isTabletDrawerPreview) return;
      if (!this.showMobilePreview) return;
      const el = event?.target;
      if (!el || typeof el.closest !== "function") return;
      if (el.closest(SHELL_CLICK_KEEPS_PREVIEW)) return;
      this.closeMobilePreview();
    },
    homeGridColumns() {
      const w = Number(this.viewportWidth || (typeof window !== "undefined" ? window.innerWidth : 0) || 0);
      const wide = String(this.homeViewMode || "wide") === "wide";
      if (w >= 1280) return wide ? 4 : 6;
      if (w >= 960) return wide ? 3 : 4;
      if (w >= 600) return wide ? 2 : 3;
      return 1;
    },
    openLongPressPicker(item, index, touch) {
      if (this._longPressAbortOpen) return;
      const rows = Array.isArray(this.filteredHomeItems) ? this.filteredHomeItems : [];
      const cols = Math.max(1, Number(this.homeGridColumns() || 1));
      const i = Math.max(0, Math.min(rows.length - 1, Number(index || 0)));
      const rowStart = Math.floor(i / cols) * cols;
      const rowItems = rows.slice(rowStart, rowStart + cols).filter((x) => String(x?.source || "") !== "folder");
      if (!rowItems.length) return;
      const selectedIndex = Math.max(0, rowItems.findIndex((x) => this.previewItemKey(x) === this.previewItemKey(item)));
      this.longPressPickerItems = rowItems;
      this.longPressPickerIndex = selectedIndex;
      this._longPressBaseIndex = selectedIndex;
      this._longPressMoveX = Number(touch?.clientX || this._longPressStartX || 0);
      this._longPressAnchorY = Number(touch?.clientY || this._longPressStartY || 0);
      this.longPressPickerOpen = true;
      this._longPressActive = true;
      this._longPressSuppressClickUntil = Date.now() + 420;
      this.setLongPressBodyLock(true);
    },
    closeLongPressPicker(force = false) {
      if (this._longPressTimer) {
        clearTimeout(this._longPressTimer);
        this._longPressTimer = null;
      }
      this._longPressActive = false;
      this.setLongPressBodyLock(false);
      if (force) {
        this._longPressSuppressClickUntil = Date.now() + 280;
      }
      this.longPressPickerOpen = false;
      this.longPressPickerItems = [];
      this.longPressPickerIndex = 0;
      this._longPressBaseIndex = 0;
      this._longPressAnchorY = 0;
      this._longPressAbortOpen = false;
    },
    onCardTouchStart(item, itemIndex, event) {
      if (Number(this.homeGridColumns() || 1) <= 1) return;
      if (String(item?.source || "") === "folder") return;
      const touch = event?.touches?.[0] || null;
      if (!touch) return;
      this.closeLongPressPicker();
      this._longPressAbortOpen = false;
      this._longPressStartX = Number(touch.clientX || 0);
      this._longPressStartY = Number(touch.clientY || 0);
      this._longPressMoveX = this._longPressStartX;
      this._longPressTimer = setTimeout(() => {
        this._longPressTimer = null;
        this.openLongPressPicker(item, itemIndex, touch);
      }, 430);
    },
    onCardTouchMove(event) {
      const touch = event?.touches?.[0] || null;
      if (!touch) return;
      const x = Number(touch.clientX || 0);
      const y = Number(touch.clientY || 0);
      if (!this._longPressActive) {
        const dx = Math.abs(x - Number(this._longPressStartX || 0));
        const dy = Math.abs(y - Number(this._longPressStartY || 0));
        if (dx > 12 || dy > 12) {
          this._longPressAbortOpen = true;
          this.closeLongPressPicker();
        }
        return;
      }
      const host = this.$refs.longPressPickerHost;
      if (host && typeof host.getBoundingClientRect === "function") {
        const rect = host.getBoundingClientRect();
        const out = x < rect.left || x > rect.right || y < rect.top || y > rect.bottom;
        if (out) {
          this._longPressAbortOpen = true;
          this.closeLongPressPicker(true);
          return;
        }
      }
      this._longPressMoveX = x;
      const step = 64;
      const delta = x - Number(this._longPressStartX || 0);
      const shift = Math.round(delta / step);
      const max = Math.max(0, (this.longPressPickerItems || []).length - 1);
      const next = Math.max(0, Math.min(max, Number(this._longPressBaseIndex || 0) + shift));
      this.longPressPickerIndex = next;
    },
    onCardTouchEnd() {
      if (!this._longPressActive) {
        this.closeLongPressPicker();
        return;
      }
      if (this._longPressAbortOpen) {
        this.closeLongPressPicker(true);
        return;
      }
      const pick = (this.longPressPickerItems || [])[Number(this.longPressPickerIndex || 0)] || null;
      this.closeLongPressPicker(true);
      if (pick) {
        this.openHomeItem(pick);
      }
    },
    onCardTouchCancel() {
      this.closeLongPressPicker(true);
    },
    async onManualLoadMoreClick() {
      const st = this.activeHomeState || {};
      if (st.loading) return;
      const toast = useToastStore();
      if (!st.hasMore) {
        toast.open(this.t("common.no_more"), "info");
        return;
      }
      await this.loadHomeFeed(false).catch(() => null);
      const nextSt = this.activeHomeState || {};
      if (!nextSt.hasMore) {
        toast.open(this.t("common.no_more"), "info");
      }
    },
    ensureLeftTabletPreviewRailMode() {
      if (!this.isTabletDrawerPreview || !this.showMobilePreview || this.previewDrawerSide !== "left") return;
      const layout = useLayoutStore();
      if (this._leftPreviewPrevRail === null) {
        this._leftPreviewPrevRail = !!layout.rail;
      }
      if (layout.rail !== true) {
        layout.rail = true;
      }
    },
    restoreLeftTabletPreviewRailMode(force = false) {
      if (this._leftPreviewPrevRail === null) return;
      if (!force && this.isTabletDrawerPreview && this.showMobilePreview && this.previewDrawerSide === "left") return;
      const layout = useLayoutStore();
      layout.rail = !!this._leftPreviewPrevRail;
      this._leftPreviewPrevRail = null;
    },
    onMobilePreviewTouchStart(event) {
      const touch = event?.touches?.[0] || null;
      this._mobilePreviewSwipeTracking = !!touch;
      if (!touch) return;
      this._mobilePreviewSwipeStartX = Number(touch.clientX || 0);
      this._mobilePreviewSwipeStartY = Number(touch.clientY || 0);
      this._mobilePreviewSwipeLastX = this._mobilePreviewSwipeStartX;
      this._mobilePreviewSwipeLastY = this._mobilePreviewSwipeStartY;
    },
    onMobilePreviewTouchMove(event) {
      if (!this._mobilePreviewSwipeTracking) return;
      const touch = event?.touches?.[0] || null;
      if (!touch) return;
      this._mobilePreviewSwipeLastX = Number(touch.clientX || this._mobilePreviewSwipeLastX || 0);
      this._mobilePreviewSwipeLastY = Number(touch.clientY || this._mobilePreviewSwipeLastY || 0);
    },
    onMobilePreviewTouchEnd(event) {
      if (!this._mobilePreviewSwipeTracking) return;
      const touch = event?.changedTouches?.[0] || null;
      const endX = Number(touch?.clientX ?? this._mobilePreviewSwipeLastX ?? this._mobilePreviewSwipeStartX ?? 0);
      const endY = Number(touch?.clientY ?? this._mobilePreviewSwipeLastY ?? this._mobilePreviewSwipeStartY ?? 0);
      const dx = endX - Number(this._mobilePreviewSwipeStartX || 0);
      const dy = endY - Number(this._mobilePreviewSwipeStartY || 0);
      this._mobilePreviewSwipeTracking = false;
      const absDx = Math.abs(dx);
      const absDy = Math.abs(dy);
      if (!this.isTabletDrawerPreview || absDx < 64 || absDx < absDy * 1.2) return;
      const closeBySwipe = (this.previewDrawerSide === "left" && dx <= -64)
        || (this.previewDrawerSide !== "left" && dx >= 64);
      if (closeBySwipe) {
        this.closeMobilePreview();
      }
    },
    onMobilePreviewTouchCancel() {
      this._mobilePreviewSwipeTracking = false;
    },
    refreshTouchInteraction() {
      if (typeof window === "undefined") {
        this.isTouchInteraction = false;
        this.viewportWidth = 0;
        return;
      }
      this.viewportWidth = Number(window.innerWidth || 0);
      const nav = typeof navigator !== "undefined" ? navigator : null;
      const maxTouchPoints = Number(nav?.maxTouchPoints || nav?.msMaxTouchPoints || 0);
      const coarse = typeof window.matchMedia === "function"
        ? !!window.matchMedia("(pointer: coarse)").matches
        : false;
      const hasTouchEvent = "ontouchstart" in window;
      this.isTouchInteraction = hasTouchEvent || maxTouchPoints > 0 || coarse;
    },
    markTouchInteraction() {
      this.isTouchInteraction = true;
    },
    onPointerDownCapture(event) {
      const pt = String(event?.pointerType || "").toLowerCase();
      if (pt === "touch" || pt === "pen") {
        this.isTouchInteraction = true;
      }
    },
    onViewportResize() {
      this.refreshTouchInteraction();
      if (typeof this.updateViewportFlags === "function") {
        this.updateViewportFlags();
      }
    },
    scopedTabQueryKey() {
      return "local_tab";
    },
    applyRouteScopedTab() {
      const key = this.scopedTabQueryKey();
      const val = String(this.$route?.query?.[key] || "").trim();
      if (!val) return;
      if (this.isTabInScope(val) && String(this.homeTab || "") !== val) {
        this.setHomeTab(val);
      }
    },
    syncRouteScopedTab() {
      const key = this.scopedTabQueryKey();
      const nextTab = String(this.homeTab || "").trim();
      if (!nextTab) return;
      const currentPath = String(this.$route?.path || "");
      if (!currentPath.startsWith("/dashboard")) {
        this._syncingRouteTab = true;
        this.$router.replace({ path: "/dashboard", query: { [key]: nextTab } }).catch(() => null).finally(() => {
          this._syncingRouteTab = false;
        });
        return;
      }
      const current = String(this.$route?.query?.[key] || "").trim();
      if (current === nextTab) return;
      this._syncingRouteTab = true;
      const nextQuery = { ...(this.$route?.query || {}), [key]: nextTab };
      this.$router.replace({ query: nextQuery }).catch(() => null).finally(() => {
        this._syncingRouteTab = false;
      });
    },
    // Dismiss the filter dialog without touching the feed. Closing is all this
    // has to do: the store rolls the live filters back on the close edge, which
    // also covers a backdrop click and Esc.
    cancelHomeFilters() {
      this.homeFiltersOpen = false;
    },
    onRefreshClick() {
      this.refreshCurrentHomeFeed({ force: true }).catch(() => null);
    },
    // A horizontal drag on the feed belongs to the shell now (it pulls the
    // sidebar out and pushes it back), and the library/favorites/history switch
    // lives in the rail. Nothing in this page may claim the horizontal axis on
    // the feed itself -- the long-press row picker is the single exception, and
    // it only starts from on top of a card.
    // --- feed scroll memory ---------------------------------------------------
    // The feed list itself survives a tab switch and a trip to the toolbox; the
    // window offset does not, because every page shares one scroller and the
    // shorter destination clamps it. These four helpers are the whole mechanism:
    // a key per feed, a read on the way in, a write on the way out.
    _feedScrollKeyFor(tabKey) {
      const tab = String(tabKey ?? this.homeTab ?? "").trim();
      if (!tab) return "";
      if (tab === "local_gallery" && this.isLocalFolderMode()) {
        const path = String(this.localFolderPath || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
        return `${tab}|folder:${path}`;
      }
      return tab;
    },
    _currentScrollY() {
      if (typeof window === "undefined") return 0;
      return Math.max(
        0,
        Number(window.scrollY || 0),
        Number(document?.documentElement?.scrollTop || 0),
        Number(document?.body?.scrollTop || 0),
      );
    },
    // True when the document is too short to honour the offset we asked for --
    // the exact signature of "the feed has not finished growing yet", and never
    // the signature of a user scrolling mid-list.
    _scrollPinnedToDocumentEnd() {
      if (typeof window === "undefined") return false;
      const viewport = Number(window.innerHeight || 0);
      const height = Math.max(
        Number(document?.documentElement?.scrollHeight || 0),
        Number(document?.body?.scrollHeight || 0),
      );
      return this._currentScrollY() + viewport >= height - 8;
    },
    _saveFeedScroll(tabKey) {
      const key = this._feedScrollKeyFor(tabKey);
      if (!key) return;
      writeFeedScroll(key, this._currentScrollY());
    },
    _restoreFeedScroll(tabKey) {
      if (typeof window === "undefined") return;
      const key = this._feedScrollKeyFor(tabKey);
      if (!key) return;
      const y = readFeedScroll(key);
      this._feedRestoreTarget = y;
      this._feedRestoreUntil = Date.now() + 350;
      if (!y) return;
      const apply = () => {
        window.scrollTo({ top: y, left: 0, behavior: "auto" });
      };
      this.$nextTick(() => {
        window.requestAnimationFrame(() => {
          apply();
          // A feed that mounts short (a reload still in flight) clamps the first
          // attempt. One retry, and only when the clamp -- not the user -- is
          // what left us somewhere else.
          window.setTimeout(() => {
            if (Date.now() > Number(this._feedRestoreUntil || 0)) return;
            if (Math.abs(this._currentScrollY() - y) <= 8) return;
            if (!this._scrollPinnedToDocumentEnd()) return;
            apply();
          }, 150);
        });
      });
    },
    onFeedScroll() {
      if (typeof window === "undefined") return;
      const y = this._currentScrollY();
      // Inside the restore window the scroll events are mostly our own scrollTo
      // landing; writing them would overwrite the memory with the clamped value.
      if (Date.now() < Number(this._feedRestoreUntil || 0)) return;
      // Every page shares the window scroller, so a scroll on the toolbox or in
      // the settings must not be filed under the library's offset.
      if (String(this.$route?.name || "") !== "dashboard") return;
      const key = this._feedScrollKeyFor(this.homeTab);
      if (!key) return;
      writeFeedScroll(key, y);
    },
    _scrollFeedToTop() {
      if (typeof window === "undefined") return;
      this._feedRestoreUntil = Date.now() + 350;
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
      // The new page gets a fresh place, so nothing re-anchors to the old one.
      this._saveFeedScroll(this.homeTab);
    },
    // --- paging ---------------------------------------------------------------
    // Every pager entry point funnels through here so the "a new page means a
    // new place" rule is written once.
    async _applyPagerMove(run) {
      const before = Number(this.feedPage || 1);
      await run();
      if (Number(this.feedPage || 1) === before) return;
      this._scrollFeedToTop();
    },
    onPagerPrev() {
      if (!this.feedCanPrev) return;
      return this._applyPagerMove(() => this.prevFeedPage().catch(() => null));
    },
    onPagerNext() {
      if (!this.feedCanNext) return;
      return this._applyPagerMove(() => this.nextFeedPage().catch(() => null));
    },
    onPagerJump(page) {
      return this._applyPagerMove(() => this.goToFeedPage(page).catch(() => null));
    },
    setLongPressBodyLock(locked) {
      if (typeof document === "undefined") return;
      const body = document.body;
      if (!body) return;
      if (locked) {
        this._longPressBodyPrevOverflow = String(body.style.overflow || "");
        this._longPressBodyPrevTouchAction = String(body.style.touchAction || "");
        body.style.overflow = "hidden";
        body.style.touchAction = "none";
        return;
      }
      body.style.overflow = String(this._longPressBodyPrevOverflow || "");
      body.style.touchAction = String(this._longPressBodyPrevTouchAction || "");
      this._longPressBodyPrevOverflow = "";
      this._longPressBodyPrevTouchAction = "";
    },
    closeDesktopHoverPreview() {
      if (this._hoverLeaveTimer) {
        clearTimeout(this._hoverLeaveTimer);
        this._hoverLeaveTimer = null;
      }
      if (this._hoverOpenTimer) {
        clearTimeout(this._hoverOpenTimer);
        this._hoverOpenTimer = null;
      }
      this._hoverPendingItem = null;
      this._hoverPendingPos = null;
      this._hoverTargetRect = null;
      this._hoverInsidePreview = false;
      this.showDesktopHoverPreview = false;
      this.desktopHoverPreviewItem = null;
    },
    clearDesktopHoverTimer() {
      if (this._hoverLeaveTimer) {
        clearTimeout(this._hoverLeaveTimer);
        this._hoverLeaveTimer = null;
      }
    },
    _hoverItemKey(item) {
      return String(item?.id || `${item?.source || ""}:${item?.arcid || ""}:${item?.gid || 0}:${item?.token || ""}`);
    },
    _openDesktopHoverPreview(item, pos) {
      this.desktopHoverPreviewItem = item || null;
      const p = pos || { x: 8, y: 8 };
      this.desktopHoverPreviewX = Number(p.x || 8);
      this.desktopHoverPreviewY = Number(p.y || 8);
      this.showDesktopHoverPreview = !!item;
      this.desktopHoverPreviewKey = Number(this.desktopHoverPreviewKey || 0) + 1;
    },
    _scheduleDesktopHoverOpen(item, event) {
      const pos = this.positionDesktopHoverPreview(event);
      if (!pos) return;
      if (this._hoverOpenTimer) {
        clearTimeout(this._hoverOpenTimer);
        this._hoverOpenTimer = null;
      }
      this._hoverPendingItem = item || null;
      this._hoverPendingPos = pos;
      this._hoverOpenTimer = setTimeout(() => {
        this._hoverOpenTimer = null;
        const pending = this._hoverPendingItem;
        const pendingPos = this._hoverPendingPos;
        this._hoverPendingItem = null;
        this._hoverPendingPos = null;
        if (!pending) return;
        this._openDesktopHoverPreview(pending, pendingPos);
      }, Math.max(250, Number(this._hoverOpenDelayMs || 1000)));
    },
    onCardMouseEnter(item, event) {
      if (this.effectivePreviewUiMode !== "desktop") return;
      if (String(item?.source || "") === "folder") return;
      const target = event?.currentTarget;
      if (target && typeof target.getBoundingClientRect === "function") {
        this._hoverTargetRect = target.getBoundingClientRect();
      }
      if (this._hoverLeaveTimer) {
        clearTimeout(this._hoverLeaveTimer);
        this._hoverLeaveTimer = null;
      }
      const currentKey = this._hoverItemKey(this.desktopHoverPreviewItem || null);
      const nextKey = this._hoverItemKey(item || null);
      if (currentKey && currentKey === nextKey && this.desktopHoverPreviewItem) {
        const pos = this.positionDesktopHoverPreview(event);
        if (pos) {
          this.desktopHoverPreviewX = Number(pos.x || 8);
          this.desktopHoverPreviewY = Number(pos.y || 8);
        }
        return;
      }
      this._scheduleDesktopHoverOpen(item, event);
    },
    onCardMouseMove(item, event) {
      if (this.effectivePreviewUiMode !== "desktop") return;
      if (String(item?.source || "") === "folder") return;
      const nextKey = this._hoverItemKey(item || null);
      const currentKey = this._hoverItemKey(this.desktopHoverPreviewItem || null);
      const pendingKey = this._hoverItemKey(this._hoverPendingItem || null);
      const pos = this.positionDesktopHoverPreview();
      if (!pos) return;
      if (currentKey && currentKey === nextKey && this.desktopHoverPreviewItem) {
        this.desktopHoverPreviewX = Number(pos.x || 8);
        this.desktopHoverPreviewY = Number(pos.y || 8);
        return;
      }
      if (pendingKey && pendingKey === nextKey) {
        this._hoverPendingPos = pos;
      }
    },
    onCardMouseLeave() {
      if (this.effectivePreviewUiMode !== "desktop") return;
      this._hoverTargetRect = null;
      if (this._hoverOpenTimer) {
        clearTimeout(this._hoverOpenTimer);
        this._hoverOpenTimer = null;
      }
      this._hoverPendingItem = null;
      this._hoverPendingPos = null;
      if (this._hoverLeaveTimer) clearTimeout(this._hoverLeaveTimer);
      this._hoverLeaveTimer = setTimeout(() => {
        if (!this._hoverInsidePreview && !this.quickTagDialogOpen) {
          this.showDesktopHoverPreview = false;
          this.desktopHoverPreviewItem = null;
        }
      }, 180);
    },
    onGhostPreviewEnter() {
      this._hoverInsidePreview = true;
      if (this._hoverLeaveTimer) {
        clearTimeout(this._hoverLeaveTimer);
        this._hoverLeaveTimer = null;
      }
    },
    onGhostPreviewLeave() {
      this._hoverInsidePreview = false;
      if (!this.quickTagDialogOpen) {
        this.showDesktopHoverPreview = false;
        this.desktopHoverPreviewItem = null;
      }
    },
    positionDesktopHoverPreview(event = null) {
      let rect = this._hoverTargetRect;
      if (!rect) {
        const target = event?.currentTarget;
        if (!target || typeof target.getBoundingClientRect !== "function") return null;
        rect = target.getBoundingClientRect();
        this._hoverTargetRect = rect;
      }
      const panelW = 480;
      const panelH = Math.round(window.innerHeight * 0.82);
      const gap = 6;
      const rightX = rect.right + gap;
      const leftX = rect.left - panelW - gap;
      let x = rightX;
      if (x + panelW > window.innerWidth - 8) x = Math.max(8, leftX);
      let y = rect.top;
      if (y + panelH > window.innerHeight - 8) y = Math.max(8, window.innerHeight - panelH - 8);
      return { x: Math.round(Math.max(8, x)), y: Math.round(Math.max(8, y)) };
    },
    showNlToggle() {
      return true;
    },
    toggleNlSearch() {
      if (!this.showNlToggle()) return;
      this.config.SEARCH_NL_ENABLED = !this.config.SEARCH_NL_ENABLED;
    },
    requestFavoriteToggle(item) {
      const key = String(item?.arcid || "").trim();
      const next = !this.isFavorited(item);
      // The previews hold *snapshot* objects (the desktop hover ghost and the
      // mobile full-screen card) while the store patches the feed rows by
      // replacing them -- so the snapshot would keep the old star forever.
      // Flip what the user is actually looking at, and undo it if the write fails.
      this._patchPreviewFavoriteSnapshot(key, next);
      this.toggleFavorite(item).then((ok) => {
        if (ok === false) this._patchPreviewFavoriteSnapshot(key, !next);
      }).catch(() => null);
    },
    _patchPreviewFavoriteSnapshot(arcid, on) {
      const key = String(arcid || "").trim();
      if (!key) return;
      const patch = (row) => {
        if (!row || String(row.arcid || "").trim() !== key) return row;
        const tags = (row.tags || [])
          .map((x) => String(x || "").trim())
          .filter(Boolean)
          .filter((x) => x.toLowerCase() !== "favorited");
        return { ...row, tags: on ? [...tags, "favorited"] : tags };
      };
      if (this.desktopHoverPreviewItem) {
        this.desktopHoverPreviewItem = patch(this.desktopHoverPreviewItem);
      }
      if (this.tempMobileItem) {
        this.tempMobileItem = patch(this.tempMobileItem);
      }
    },
    requestLocalDelete(item) {
      const src = String(item?.source || "").trim();
      const arcid = String(item?.arcid || "").trim();
      if (src !== "works" || !arcid) return;
      this.deleteDialogItem = item;
      this.deleteDialogDeleteFiles = false;
      this.deleteDialogDeleteDb = false;
      this.deleteDialogDeleteReadEvents = false;
      this.deleteDialogDangerConfirmed = false;
      this.deleteDialogOpen = true;
    },
    async applyLocalDelete() {
      const item = this.deleteDialogItem;
      this.deleteDialogOpen = false;
      this.deleteDialogItem = null;
      if (!item) return;
      const arcid = String(item?.arcid || "").trim();
      if (!arcid) return;
      try {
        await deleteLocalGallery({
          arcid,
          delete_files: !!this.deleteDialogDeleteFiles,
          delete_db: !!this.deleteDialogDeleteDb,
          delete_read_events: !!this.deleteDialogDeleteReadEvents,
        });
        await this.resetHomeFeed();
      } catch (_e) {
        // store/api layer handles error text elsewhere
      }
    },
    customNamespaceDefs() {
      const settingsStore = useSettingsStore();
      return Array.isArray(settingsStore?.customNamespaceDefs) ? settingsStore.customNamespaceDefs : [];
    },
    // Every namespace the quick-add picker can offer: built-ins plus the custom
    // ones defined in settings.
    quickTagNamespaceOptions() {
      const custom = this.customNamespaceDefs();
      const out = [];
      const seen = new Set();
      const push = (rawKey) => {
        const key = normalizeNamespaceKey(rawKey, { fallbackToOther: false });
        if (!key || seen.has(key)) return;
        seen.add(key);
        out.push({ title: getNamespaceDisplayLabel(key, this.t, custom), value: key });
      };
      for (const def of BUILTIN_NAMESPACE_DEFS) push(def?.key);
      for (const def of custom || []) push(def?.key);
      return out;
    },
    categoryLabelFor(cat) {
      return getCategoryLabel(cat, this.t);
    },
    displayQuickTag(tag) {
      return stripUserTagMarker(tag);
    },
    // Switching namespace invalidates the suggestion list: it was filtered to
    // the old namespace on purpose.
    onQuickTagNamespaceChange(v) {
      this.quickTagSuggestSeq += 1;
      this.quickTagNs = normalizeNamespaceKey(v || "other", { fallbackToOther: true }) || "other";
      this.quickTagSuggest = [];
      const kw = String(this.quickTagSearch || "").trim();
      if (kw) this.onQuickTagSearch(kw);
    },
    /**
     * Enter (or the add button) turns the box contents into a tag.
     *
     * The namespace is a separate control, so the typed text IS the value -- a
     * phrase that matched no suggestion is added just the same. An explicit
     * `ns:value` (e.g. a cross-namespace suggestion) is honored as-is; the
     * picked namespace is only the fallback.
     */
    commitQuickTag() {
      const label = String(this.quickTagSearch || "").trim();
      if (!label) return;
      const ns = normalizeNamespaceKey(this.quickTagNs, { fallbackToOther: true }) || "other";
      const full = normalizeUserTagInput(label, { fallbackNs: ns });
      if (!full) return;
      this.quickTagSuggestSeq += 1;
      const next = Array.isArray(this.quickTagInput) ? this.quickTagInput : [];
      if (!next.some((x) => String(x).toLowerCase() === full.toLowerCase())) {
        this.quickTagInput = [...next, full];
      }
      this.quickTagSearch = "";
      this.quickTagSuggest = [];
    },
    pickQuickTagSuggestion(label) {
      this.quickTagSearch = String(label || "").trim();
      this.commitQuickTag();
    },
    removeQuickTag(tag) {
      const key = String(tag || "").toLowerCase();
      this.quickTagInput = (this.quickTagInput || []).filter((x) => String(x).toLowerCase() !== key);
    },
    openQuickTagDialog(item) {
      const it = item || null;
      if (String(it?.source || "") !== "works") return;
      if (!String(it?.arcid || "").trim()) return;
      this.quickTagSuggestSeq += 1;
      this.quickTagItem = it;
      this.quickTagNs = "other";
      this.quickTagInput = [];
      this.quickTagSearch = "";
      this.quickTagSuggest = [];
      this.quickTagDialogOpen = true;
      this._hoverInsidePreview = true;
      this.showDesktopHoverPreview = false;
      this.desktopHoverPreviewItem = null;
    },
    closeQuickTagDialog() {
      this.quickTagSuggestSeq += 1;
      this.quickTagDialogOpen = false;
      this.quickTagSaving = false;
      this.quickTagItem = null;
      this.quickTagNs = "other";
      this.quickTagInput = [];
      this.quickTagSearch = "";
      this.quickTagSuggest = [];
      this._hoverInsidePreview = false;
    },
    async onQuickTagSearch(q) {
      const seq = ++this.quickTagSuggestSeq;
      const kw = String(q || "").trim();
      if (!kw) {
        this.quickTagSuggest = [];
        return;
      }
      // Suggestions are fetched per keystroke, so a slow early reply must not
      // overwrite the list a later one produced.
      const ns = this.quickTagNs;
      try {
        const res = await getHomeTagSuggest({ q: kw, limit: 20, ui_lang: String(this.config?.DATA_UI_LANG || "zh") });
        if (seq !== this.quickTagSuggestSeq) return;
        this.quickTagSuggest = tagSuggestLabels(Array.isArray(res?.items) ? res.items : [], ns);
      } catch {
        if (seq !== this.quickTagSuggestSeq) return;
        this.quickTagSuggest = [];
      }
    },
    async applyQuickTagDialog() {
      const arcid = String(this.quickTagItem?.arcid || "").trim();
      if (!arcid) {
        this.closeQuickTagDialog();
        return;
      }
      this.commitQuickTag();
      const add = (this.quickTagInput || []).filter(Boolean);
      if (!add.length) {
        this.closeQuickTagDialog();
        return;
      }
      const ns = normalizeNamespaceKey(this.quickTagNs, { fallbackToOther: true }) || "other";
      this.quickTagSaving = true;
      try {
        await batchUpdateLocalMeta({ arcids: [arcid], namespace: ns, add_user_tags: add, remove_user_tags: [], clear_user_title: false });
        this.closeQuickTagDialog();
        await this.resetHomeFeed();
      } catch (e) {
        this.quickTagSaving = false;
        useToastStore().open(String(e?.response?.data?.detail || e), "warning");
      }
    },
    async onPreviewApplyTagFilter(payload) {
      const tag = String(typeof payload === "object" && payload !== null ? (payload.tag || "") : (payload || "")).trim();
      if (!tag) return;
      if (this.effectivePreviewUiMode === "desktop") {
        this.showDesktopHoverPreview = false;
        this._hoverInsidePreview = false;
      }
      this.tagExploreSeedTag = tag;
      this.tagExploreOpen = true;
    },
    closeAllOverlayPanels() {
      this.quickSearchOpen = false;
      this.imageSearchDialog = false;
      this.homeFiltersOpen = false;
      this.localSortOpen = false;
      this.favoriteDialogOpen = false;
      this.deleteDialogOpen = false;
      this.quickTagDialogOpen = false;
      this.tagExploreOpen = false;
      this.tagExploreSeedTag = "";
      const hasPv = this.useRoutePreview && !!String(this.$route?.query?.pv || "").trim();
      if (hasPv) {
        const q = { ...(this.$route?.query || {}) };
        delete q.pv;
        this.mobilePreviewItem = null;
        this.tempMobileItem = null;
        this.$router.replace({ query: q }).catch(() => null);
      } else {
        this.mobilePreviewItem = null;
        this.tempMobileItem = null;
      }
      this.restoreLeftTabletPreviewRailMode(true);
    },
    _mergeHydratedItem(current, incoming) {
      const cur = (current && typeof current === "object") ? current : {};
      const row = (incoming && typeof incoming === "object") ? incoming : {};
      return {
        ...cur,
        ...row,
        meta: { ...(cur.meta || {}), ...(row.meta || {}) },
        raw: { ...(cur.raw || {}), ...(row.raw || {}) },
        tags: Array.isArray(row.tags) ? row.tags : (cur.tags || []),
        tags_translated: Array.isArray(row.tags_translated) ? row.tags_translated : (cur.tags_translated || []),
      };
    },
    onPreviewHydrated(item) {
      this.applyHydratedEhItem(item);
      const key = this.previewItemKey(item);
      if (!key) return;
      if (this.previewItemKey(this.desktopHoverPreviewItem) === key && this.desktopHoverPreviewItem) {
        this.desktopHoverPreviewItem = this._mergeHydratedItem(this.desktopHoverPreviewItem, item);
      }
      if (this.previewItemKey(this.mobilePreviewItem) === key && this.mobilePreviewItem) {
        this.mobilePreviewItem = this._mergeHydratedItem(this.mobilePreviewItem, item);
      }
      if (this.previewItemKey(this.tempMobileItem) === key && this.tempMobileItem) {
        this.tempMobileItem = this._mergeHydratedItem(this.tempMobileItem, item);
      }
    },
    applyReaderOriginRestore() {
      if (typeof window === "undefined") return;
      let payload = null;
      try {
        const raw = window.sessionStorage.getItem("zgl_reader_origin");
        if (raw) payload = JSON.parse(raw);
      } catch {
        payload = null;
      }
      if (!payload || typeof payload !== "object") return;
      try {
        window.sessionStorage.removeItem("zgl_reader_origin");
      } catch {
        // ignore
      }
      const tab = String(payload.tab || "").trim();
      const legacy = {
        recommend: "local_gallery",
        favorite: "local_favorite",
        local: "local_gallery",
        history: "local_history",
        search: this.scopeDefaultTab(),
      };
      const mappedTab = legacy[tab] || tab;
      if (["local_gallery", "local_favorite", "local_history"].includes(mappedTab) && this.isTabInScope(mappedTab)) {
        this.setHomeTab(mappedTab);
      }
      const vm = String(payload.viewMode || "").trim();
      if (["wide", "compact", "list"].includes(vm)) {
        this.homeViewMode = vm;
      }
      const restoreOverlay = payload.tagExploreOpen === true;
      if (restoreOverlay) {
        this.tagExploreSeedTag = String(payload.tagExploreSeedTag || "").trim();
        this.tagExploreOpen = true;
      }
      const pv = String(payload.pv || "").trim();
      if (this.useRoutePreview && pv && String(this.$route?.query?.pv || "").trim() !== pv) {
        const q = { ...(this.$route?.query || {}), pv };
        this.$router.replace({ query: q }).catch(() => null);
      }
      const y = Number(payload.scrollY || 0);
      this.$nextTick(() => {
        if (Number.isFinite(y) && y > 0) {
          window.requestAnimationFrame(() => {
            window.scrollTo({ top: y, left: 0, behavior: "auto" });
          });
        }
      });
    },
    startReader(item, page = 1) {
      const src = String(item?.source || "").trim();
      if (src === "folder") return;
      const arcid = String(item?.arcid || "").trim();
      const p = Math.max(1, Math.floor(Number(page || 1)));
      if (src !== "works" || !arcid) return;
      // Hand the reader the order the user was actually looking at, so its end
      // screen can offer "next gallery" without the client having to replay the
      // feed's sort. `filteredHomeItems` is exactly what is on screen.
      try {
        useReaderQueueStore().setQueue(
          (this.filteredHomeItems || []).map((row) => ({
            arcid: row?.arcid,
            __queue_title: this.getGalleryTitle(row),
          })),
          String(this.homeTab || ""),
        );
      } catch {
        // a missing queue only costs the "next gallery" affordance
      }
      // Keep the preview route and selection in history for mobile Back.
      if (typeof window !== "undefined") {
        const currentPv = String(this.$route?.query?.pv || "").trim();
        const payload = {
          tab: String(this.homeTab || "local_gallery"),
          viewMode: String(this.homeViewMode || "wide"),
          scrollY: Number(window.scrollY || 0),
          tagExploreOpen: this.tagExploreOpen === true,
          tagExploreSeedTag: String(this.tagExploreSeedTag || ""),
          pv: currentPv,
          at: Date.now(),
        };
        try {
          window.sessionStorage.setItem("zgl_reader_origin", JSON.stringify(payload));
        } catch {
          // ignore
        }
      }
      this.$router.push({
        name: "reader",
        params: { arcid },
        query: { page: String(p), origin: "dashboard" },
      }).catch(() => null);
    },
    startReaderAtPage(payload) {
      const it = payload?.item || null;
      const page = Number(payload?.page || 1);
      if (!it) return;
      this.startReader(it, page);
    },
    onImageLoaded(item) {
      if (!item) return;
      item._is_retrying = false;
      item._retries = 0;
    },
    onImageError(item) {
      if (!item || !item.thumb_url || item._is_retrying) return;
      if (item._retries === undefined) item._retries = 0;
      if (item._retries >= 5) {
        const backup = String(item._thumb_backup || "").trim();
        const cur = String(item.thumb_url || "").trim();
        if (backup && backup !== cur) {
          item._retries = 0;
          item.thumb_url = backup;
        } else if (typeof this.showImageLoadTraceback === "function") {
          this.showImageLoadTraceback(item, cur || item._thumb_primary || "").catch(() => null);
        }
        return;
      }

      item._retries += 1;
      item._is_retrying = true;

      const retryDelayMs = Math.min(3200, 800 + (item._retries * 550));
      const primaryUrl = String(item._thumb_primary || item.thumb_url || "").trim();
      const backupUrl = String(item._thumb_backup || "").trim();
      const activeUrl = String(item.thumb_url || "").trim();
      const baseOriginal = activeUrl || primaryUrl;

      setTimeout(() => {
        let baseUrl = baseOriginal.replace(/([?&])r=\d+/g, "").replace(/[?&]$/, "");
        if (backupUrl && baseUrl === primaryUrl && item._retries >= 3) {
          baseUrl = backupUrl;
        }
        if (!baseUrl) {
          item._is_retrying = false;
          return;
        }
        const separator = baseUrl.includes("?") ? "&" : "?";
        const testUrl = `${baseUrl}${separator}r=${Date.now()}-${item._retries}`;

        const ghostImg = new Image();
        let settled = false;
        const timeoutId = setTimeout(() => {
          if (settled) return;
          settled = true;
          item._is_retrying = false;
          this.onImageError(item);
        }, 9000);
        ghostImg.onload = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timeoutId);
          item.thumb_url = testUrl;
          item._is_retrying = false;
        };
        ghostImg.onerror = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timeoutId);
          item._is_retrying = false;
          this.onImageError(item);
        };
        ghostImg.src = testUrl;
      }, retryDelayMs);
    },
    previewItemKey(item) {
      const src = String(item?.source || "").trim().toLowerCase();
      if (src === "works") {
        const arcid = String(item?.arcid || "").trim();
        return arcid ? `works:${arcid}` : "";
      }
      return "";
    },
    findPreviewItemByKey(key, rows = null) {
      const k = String(key || "").trim();
      if (!k) return null;
      const list = Array.isArray(rows)
        ? rows
        : (Array.isArray(this.filteredHomeItems) ? this.filteredHomeItems : []);
      return list.find((it) => this.previewItemKey(it) === k) || null;
    },
    syncMobilePreviewFromRoute() {
      if (!this.useRoutePreview) {
        this.mobilePreviewItem = null;
        this.tempMobileItem = null;
        this.restoreLeftTabletPreviewRailMode(true);
        return;
      }
      const pv = String(this.$route?.query?.pv || "").trim();
      if (!pv) {
        this.mobilePreviewItem = null;
        this.tempMobileItem = null;
        this.restoreLeftTabletPreviewRailMode(true);
        return;
      }
      const hit = this.findPreviewItemByKey(pv)
        || this.findPreviewItemByKey(pv, Array.isArray(this.activeHomeState?.items) ? this.activeHomeState.items : [])
        || ((this.previewItemKey(this.tempMobileItem) === pv) ? this.tempMobileItem : null);
      if (hit) {
        this.mobilePreviewItem = hit;
        this.tempMobileItem = hit;
        this.ensureLeftTabletPreviewRailMode();
        return;
      }
      this.mobilePreviewItem = null;
      this.restoreLeftTabletPreviewRailMode(true);
    },
    openDetailCard(item) {
      if (String(item?.source || "") === "folder") {
        this.enterLocalFolderFromItem(item).catch(() => null);
        return;
      }
      const key = this.previewItemKey(item);
      this.tempMobileItem = item || null;
      this.mobilePreviewItem = item || null;
      if (!this.useRoutePreview || !key) return;
      const cur = String(this.$route?.query?.pv || "").trim();
      if (cur === key) return;
      const q = { ...(this.$route?.query || {}), pv: key };
      this.$router.push({ query: q }).catch(() => null);
    },
    closeMobilePreview() {
      const hasPv = !!String(this.$route?.query?.pv || "").trim();
      if (!hasPv) {
        this.mobilePreviewItem = null;
        this.tempMobileItem = null;
        this.restoreLeftTabletPreviewRailMode(true);
        return;
      }
      this.$router.back();
      setTimeout(() => {
        const stillPv = String(this.$route?.query?.pv || "").trim();
        if (!stillPv) {
          this.mobilePreviewItem = null;
          this.tempMobileItem = null;
          this.restoreLeftTabletPreviewRailMode(true);
          return;
        }
        const q = { ...(this.$route?.query || {}) };
        delete q.pv;
        this.$router.replace({ query: q }).catch(() => null).finally(() => {
          this.restoreLeftTabletPreviewRailMode(true);
        });
      }, 320);
    },
    openHomeItem(item) {
      if (String(item?.source || "") === "folder") {
        this.enterLocalFolderFromItem(item).catch(() => null);
        return;
      }
      if (this.useRoutePreview) {
        this.openDetailCard(item);
        return;
      }
      this.onCoverClick(item);
    },
    isLocalScope() {
      return true;
    },
    scopeDefaultTab() {
      return "local_gallery";
    },
    isTabInScope(tab) {
      const t = String(tab || "");
      return t.startsWith("local_");
    },
    ensureScopeTab() {
      const current = String(this.homeTab || "");
      if (!this.isTabInScope(current)) {
        this.setHomeTab(this.scopeDefaultTab());
      }
    },
    isPlaceholderHomeTab() {
      return false;
    },
    placeholderHomeTitle() {
      const key = String(this.homeTab || "");
      return this.t("home.placeholder.title");
    },
  },
};
</script>

<style scoped>
/* The rail owns the library/favorites/history switch, so this row only carries
   the view-mode toggle and stays right-aligned on every breakpoint. */
.home-tab-row-mobile {
  align-items: stretch;
}

.home-tab-row-mobile .home-view-toggle {
  margin-left: auto;
}

.home-view-toggle {
  gap: 8px;
  overflow: visible;
  border: 0;
  background: transparent !important;
}

.home-view-toggle :deep(.v-btn) {
  min-width: 74px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.18) !important;
  border-radius: 999px !important;
}

.mobile-action-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.mobile-action-btn {
  min-width: 0;
}

.mobile-category-grid {
  justify-content: center;
}

.mobile-category-btn {
  min-width: 138px;
  width: 138px;
  padding-inline: 6px !important;
}

.home-items-zone {
  min-height: 42vh;
  touch-action: pan-y;
}

.home-card,
.home-card * {
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}

.longpress-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2790;
  background: rgba(18, 22, 30, 0.36);
  pointer-events: auto;
}

.longpress-picker-host {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 2800;
  display: flex;
  justify-content: center;
  pointer-events: auto;
}

.longpress-picker-card {
  width: auto;
  max-width: 92vw;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.16);
  background: rgba(var(--v-theme-surface), 0.96);
  border-radius: 14px;
  padding: 10px 8px 8px;
  box-sizing: border-box;
}

.longpress-picker-track {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  gap: 5px;
  align-items: end;
  padding: 0;
}

.longpress-picker-item {
  width: 100%;
  min-width: 0;
  transform: scale(0.9);
  transition: transform 0.16s ease, opacity 0.16s ease;
  opacity: 0.92;
}

.longpress-picker-item.active {
  transform: scale(1);
  opacity: 1;
}

.longpress-picker-item.inactive {
  opacity: 0.84;
}

.longpress-picker-thumb-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.2);
}

.longpress-picker-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  -webkit-touch-callout: none;
  user-select: none;
  -webkit-user-drag: none;
  pointer-events: none;
}

.longpress-picker-thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(var(--v-theme-on-surface), 0.56);
  background: rgba(var(--v-theme-surface-variant), 0.4);
}

.longpress-picker-mask {
  position: absolute;
  inset: 0;
  background: rgba(25, 30, 40, 0.42);
}

.longpress-picker-title {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.25;
  color: rgba(var(--v-theme-on-surface), 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dashboard-page-shell {
  --tablet-preview-pane-width: min(460px, 92vw);
  --app-sidebar-rail-width: 56px;
  overflow-x: clip;
}

@media (min-width: 768px) {
  .dashboard-page-shell {
    --tablet-preview-pane-width: 440px;
  }

  .dashboard-page-shell.tablet-preview-open-right {
    padding-right: var(--tablet-preview-pane-width);
  }
}

.mobile-preview-fullscreen {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  max-width: 100%;
  min-width: 0;
  z-index: 2500;
  background: rgba(var(--v-theme-background), 0.98);
  display: flex;
  flex-direction: column;
}

.mobile-preview-fullscreen.tablet-preview-drawer {
  left: auto;
  right: 0;
  width: var(--tablet-preview-pane-width);
  border-left: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  box-shadow: -12px 0 32px rgba(0, 0, 0, 0.55);
  background: rgba(var(--v-theme-surface), 0.98);
  transform: translateZ(0);
  backface-visibility: hidden;
  will-change: transform, opacity;
  contain: layout paint;
}

.mobile-preview-fullscreen.tablet-preview-drawer.drawer-left {
  left: var(--app-sidebar-rail-width);
  right: auto;
  border-left: 0;
  border-right: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  box-shadow: 12px 0 32px rgba(0, 0, 0, 0.55);
  z-index: 1004;
}

.mobile-preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  background: rgba(var(--v-theme-surface), 0.92);
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.12);
}

.mobile-preview-body {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
  background: rgba(var(--v-theme-background), 0.98);
}

.mobile-preview-body > .v-card {
  flex: 1;
  overflow-y: auto;
}

.mobile-preview-body :deep(.preview-card) {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  max-height: none;
  height: 100%;
  border-radius: 0;
}

.mobile-preview-fullscreen.tablet-preview-drawer .mobile-preview-body :deep(.preview-card) {
  width: 100%;
}

.cookie-empty-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.desktop-hover-ghost {
  position: fixed;
  z-index: 2500;
  pointer-events: auto;
  animation: fade-in 0.2s ease-out forwards;
}

.preview-slide-up-enter-active,
.preview-slide-up-leave-active {
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.22s ease;
}

.preview-slide-up-enter-from,
.preview-slide-up-leave-to {
  transform: translateY(24px);
  opacity: 0;
}

.preview-slide-side-enter-active,
.preview-slide-side-leave-active {
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s ease;
}

.preview-slide-side-enter-from.mobile-preview-fullscreen.tablet-preview-drawer.drawer-right,
.preview-slide-side-leave-to.mobile-preview-fullscreen.tablet-preview-drawer.drawer-right {
  transform: translate3d(100%, 0, 0);
  opacity: 0.96;
}

.preview-slide-side-enter-from.mobile-preview-fullscreen.tablet-preview-drawer.drawer-left,
.preview-slide-side-leave-to.mobile-preview-fullscreen.tablet-preview-drawer.drawer-left {
  transform: translate3d(-100%, 0, 0);
  opacity: 0.96;
}

@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Keep both fields usable on narrow phones; the action gets its own row. */
.quick-tag-composer {
  display: grid;
  grid-template-columns: clamp(96px, 38%, 132px) minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.quick-tag-ns {
  min-width: 0;
}

.quick-tag-input {
  min-width: 0;
}

.quick-tag-add {
  grid-column: 2;
  justify-self: end;
}

.tag-suggest-chip {
  border: 1px solid rgba(148, 163, 184, 0.5);
}

/* Keeps the staged-tag strip from collapsing the dialog when it is empty. */
.quick-tag-staged {
  min-height: 32px;
}

</style>
