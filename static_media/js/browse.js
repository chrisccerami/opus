var o_browse = {

     /**
      *
      *  all the things that happen on the browse tab
      *
      **/

    browseBehaviors: function() {

        // add a new range pair
        $('.addrange', '#browse').live("click", function() {
            if ($('.addrange', '#browse').text() != "add range") {
                alert('please select an observation to begin your range');
                return false;
            }
            opus.addrange_clicked = true;
            $('.addrange','#browse').text("select range start");
            return false;
        });

        //hover states on the static widgets
		$('.gallery_icons li.ui-state-default, .chosen_column_close', '#browse').live({
                mouseenter:
			        function() { $(this).addClass('ui-state-hover'); },
			    mouseleave:
			        function() { $(this).removeClass('ui-state-hover'); }
		});



        // gallery and table checkboxes
        // $('.gallery_icons input, .data_table input','#browse').live("click", function() {
        $('.gallery_icons input, .data_table input').live("click", function() {
            ring_obs_id = $(this).attr("id").split('__')[1]
            $(this).is(':checked') ? action = 'add' :  action = 'remove';

            // make sure the checkbox for this observation in the other view (either data or gallery)
            // is also checked/unchecked - if that view is drawn
            browse_views = ['data','gallery'];
            for (key in browse_views) {
                bview = browse_views[key]
                checked = false;
                if (action == 'add') checked = true;
                try {
                    $('#' + bview + 'input__' + ring_obs_id).attr('checked',checked)
                } catch(e) { } // view not drawn yet so no worries
            }

            if (!opus.addrange_clicked) {
                o_collections.editCollection(ring_obs_id,action);
            } else {
                // addrange clicked
                element = "li"
                if (opus.prefs.browse == 'data') {
                        element = "td";
                }
                if (!opus.addrange_min) {
                    // this is the min side of the range
                    $('.addrange','#browse').text("select range end");
                    index = $(element).index($(this).parent());
                    opus.addrange_min = { "index":index, "ring_obs_id":ring_obs_id }
                } else {
                    // we have both sides of range
                    $('.addrange','#browse').text("add range");
                    index = $(element).index($(this).parent());
                    if (index > opus.addrange_min['index']) {
                        range = opus.addrange_min['ring_obs_id'] + "," + ring_obs_id;
                        o_browse.checkRangeBoxes(opus.addrange_min['ring_obs_id'], ring_obs_id);
                    } else {
                        // user clicked later box first, reverse them for server..
                        range = ring_obs_id + "," + opus.addrange_min['ring_obs_id'];
                        o_browse.checkRangeBoxes(ring_obs_id, opus.addrange_min['ring_obs_id']);
                    }
                    opus.addrange_clicked = false;
                    opus.addrange_min = false;
                    o_collections.editCollection(range,'addrange');
                }
            }
        });



        view_info = o_browse.getViewInfo();
        namespace = view_info['namespace'];
        view_var = view_info['view_var'];
        prefix = view_info['prefix'];
        add_to_url = view_info['add_to_url'];

        // change to gallery view
        $('.gallery_view').live('click',function() {
            o_browse.browseControlIndicator('.gallery_view');
            if (opus.prefs[prefix + 'browse'] == 'data') {
                opus.prefs[prefix + 'browse'] = 'gallery';
                o_hash.updateHash();
                $('.data_container', namespace).hide();
                $('.gallery', namespace).show();
                if (!$('.gallery ul', namespace).length) {
                    o_browse.getBrowseTab();
                }
            }
            return false;
        });

        // change to data view
        $('.data_view').live('click',function() {
            o_browse.browseControlIndicator('.data_view');
            if (opus.prefs[prefix + 'browse'] == 'gallery') {
                opus.prefs[prefix + 'browse'] = 'data';
                o_hash.updateHash();
                $('.gallery', namespace).hide();
                $('.data_container',namespace).show();
                if (!$('.data_table', namespace).length) {
                    o_browse.getBrowseTab();
                }

            }
            return false;
        });


        /* we are making this default no click necessary
        $('.browse_footer', '#browse').bind('click', function() {
           o_browse.GalleryFooterClick();
        });
        */

        // results paging
        $('.next, .prev').live('click', function() {
            // all this does is update the number that shows in the box and then calls textInputMonitor
            page_no_elem = $(this).parent().next().find('.page_no');
            this_page = parseInt(page_no_elem.val());
            if ( $(this).hasClass("next")) {
                page = this_page + 1;
            } else if ($(this).hasClass("prev")) {
                 page = this_page - 1;
            }
            page_no_elem.val(page);
            o_browse.textInputMonitor(page_no_elem.attr("id"),500);
            return false;
        });

        // change page
        $('#page_no','#browse').live("change",function() {
            page = parseInt($(this).val());
            o_browse.updatePage(page);
        });
        $('#colls_page_no','#collections').live("change",function() {
            page = parseInt($(this).val());
            o_browse.updatePage(page);
        });


        // gallery thumbnail behaviors
        $('.get_detail_icon','#browse').live('click', function() {
            var ring_obs_id = $(this).attr("id").split('__')[1].split('/').join('-');

            // now ajax get the detail page:
            o_detail.getDetail(ring_obs_id);

            }); // end live

        // back to top link at bottom of gallery
        $('a[href=#top]','#browse').live('click',function() {
            $('html, body').animate({scrollTop:0}, 'slow');
            return false;
        });



        // this controls the page indicator bars you get with infinie scroll
        $(window).scroll(function() {
             o_browse.fixBrowseControls();
          });

        // close/open column chooser
        $('.get_column_chooser').live('click', function() {
                o_browse.getColumnChooser();
                return false;
        });

    },

    browseControlIndicator: function(id) {
        view_info = o_browse.getViewInfo();
        namespace = view_info['namespace'];
        view_var = view_info['view_var'];
        prefix = view_info['prefix'];
        add_to_url = view_info['add_to_url'];

        // show on the browse menu container what view we are in.
        $('.browse_controls li', namespace).removeClass('view_indicator');
        if (id) {
            $(id).parent().addClass('view_indicator');
            return;
        }
        switch (opus.prefs[prefix+'browse']) {
            case 'data':
                $('.data_view', namespace).parent().addClass('view_indicator');
                break;

            default:
                $('.gallery_view', namespace).parent().addClass('view_indicator');
        }
    },

    addColumnChooserBehaviors: function() {

        $('#column_chooser .close').click(function() {
             $('#column_chooser').jqmHide();
             return false;
        });


        $('.menu_list li a','#browse').click(function() {
            input = $(this).parent().find('input');
            if (!input.attr('checked')) {
                input.attr('checked',true);
            } else {
                input.attr('checked',false);
            }
            input.change(); // you have to do this to get the change event below to fire
            return false;
        });

        $('.chosen_column_close').live("click",function() {
            slug = $(this).parent().attr('id').split('__')[1];
            input = $('#column_chooser_input__' + slug);
            input.attr('checked',false);
            input.change();
        });

        $('.column_checkbox input[type="checkbox"].param_input', '#browse').change(function() {
            slug = $(this).data('slug');
            label = $(this).data('label');
            cols = opus.prefs['cols'];


            if ($(this).is(':checked')) {
                // checkbox is checked
                if (jQuery.inArray(slug,cols) < 0) {
                    // this slug was previously unselected, add to cols
                    // $('#cchoose__' + slug).fadeOut().remove();
                    $('<li id = "cchoose__' + slug + '">' + label + '<span class = "chosen_column_close">X</span></li>').hide().appendTo('.chosen_columns>ul').fadeIn();
                    cols.push(slug);
                }
            } else {

                // checkbox is unchecked
                if (jQuery.inArray(slug,cols) > -1) {
                    // slug had been checked, removed from the chosen
                    cols.splice(jQuery.inArray(slug,cols),1);

                    $('#cchoose__' + slug).fadeOut(function() {
                        $(this).remove();
                    });
                }
            }
            opus.prefs['cols'] = cols;
            o_hash.updateHash();
            o_browse.updateBrowse();
         });

         $('#column_chooser .cats input[type="checkbox"].cat_input').click(function() {
             cols = opus.prefs['cols'];

             if ($(this).is(':checked')) {
                 // group header checkbox is checked, now check all params in group
                 $(this).parent().parent().find('.menu_list input[type="checkbox"]').each(function() {
                     $(this).attr('checked',true);
                     slug = $(this).data('slug');
                     label = $(this).data('label');
                     if (jQuery.inArray(slug,cols) < 0) {
                         // this slug was previously unselected, add to cols
                         cols.push(slug);
                         $('<li id = "cchoose__' + slug + '">' + label + '<span class = "chosen_column_close">X</span></li>').hide().appendTo('.chosen_columns>ul').fadeIn();
                     }
                 });

             } else {
                 // deselect all in this category
                 $(this).parent().parent().find('.menu_list input[type="checkbox"]').each(function() {
                     $(this).attr('checked',false);
                     var slug = $(this).data('slug');
                     if (jQuery.inArray(slug,cols) > -1) {
                         cols.splice(jQuery.inArray(slug,cols),1);
                         $('#cchoose__' + slug).fadeOut(function() {
                             $(this).remove();
                         });
                     }
                 });
             }
             opus.prefs['cols'] = cols;
             o_hash.updateHash();
             o_browse.updateBrowse();
         });
    },

    fixBrowseControls: function() {
        return;
        /**
        if (opus.prefs.view != "browse") return;

        window_scroll = $(window).scrollTop();

        if (!window_scroll) {
            // we are at teh top of page
            if (opus.current_fixed_bar) {
                // we scrolled to top from elsewhere, unfix the control bar
                $(opus.current_fixed_bar).removeClass('browse_fixed');
            }
            return;
        }

        // this is for fixing the browse_controls
        if (o_browse.isScrolledIntoView('.browse_controls_container')) {
            if (opus.browse_controls_fixed) {
                // browse controls container is in view,
                // but browse controls are still fixed at top of page, move it back
                opus.browse_controls_fixed = false;
                $('.browse_controls','#browse').removeClass('browse_fixed');
            }
        } else {
            if (!opus.browse_controls_fixed) {
                // user is scrolling down the page and gallery controls have floated away
                // bring them back to top of page so they can be accessed
                opus.browse_controls_fixed = true;
                $('.browse_controls').addClass("browse_fixed");
            }
        }
        **/
    },


    /*
    // this is a lot of crap for keeping track of scroll position for when user returns to the page from another page - to be coninued
     $(window).resize(function() {
         // browser has been resized!
         // reset any page_bar locations
         for (element in opus.page_bar_offsets) {
             if (opus.page_bar_offsets[element]) { // only if they've already been set
                 opus.page_bar_offsets[element] = Math.floor($(element).parent().offset().top);
             }
         }
    });


    // see element name of current page showing
    // used to scroll to same location when switching from table to gallery view
    currentPageInView: function() {

        last_element = '';
        greater_than_found = false;
        page = false;

        window_scroll = $(window).scrollTop();

        for (element in opus.page_bar_offsets) {

            if (!opus.page_bar_offsets[element]) {
                // this one hasn't been set yet, find location of this page bar element
                opus.page_bar_offsets[element] = Math.floor($(element).parent().offset().top);
            }

            scrolltop = opus.page_bar_offsets[element];


            if (window_scroll >= scrolltop) {
                // user has scrolled past this element
                greater_than_found = true;
            } else if (greater_than_found) {
                    // this element is less than the scroll pos and the last element was greater
                    // so the last element is what page we are on
                    page = $(last_element).attr("id").split('__')[1];
                    break; // got what we wanted
            }

            last_element=element;
        }

        if (!page) {
            if (greater_than_found) {
                page = $(last_element).attr("id").split('__')[1];
            } else {
                page = opus.prefs.page;
            }
        }
        return 'inifite_scroll_' + opus.prefs.browse + '__' + page;
    },

    */

    checkRangeBoxes: function(ring_obs_id1, ring_obs_id2) {
        elements = ['#gallery__','#data__'];
        for (key in elements) {
            element = elements[key];
            next_id = ring_obs_id1;
            while (next_id != ring_obs_id2) {
                next = $(element + next_id, '#browse').next()
                if (next.hasClass("inifite_scroll_page")) {
                    // this is the infinite scroll indicator, continue to next
                    next = $(element + next_id, '#browse').next().next();
                }
                $(next).find('input').attr('checked',true);
                try {
                    next_id = $(next).attr("id").split('__')[1];
                } catch(e) {
                    break;  // no next_id means the view isn't drawn, so we don't need to worry about it
                }
            }
        }
    },

    createTooltip: function(element, title) {
        $(element).jqm();

    },


    startDataTable: function(namespace) {
        url = '/opus/table_headers.html?' + o_hash.getHash() + '&reqno=' + opus.lastRequestNo;
        if (namespace == '#collections') {
            url += '&colls=true'
        }
        $.ajax({ url: url,
                success: function(html) {
                    $('.data_container', namespace).html(html);
                    o_browse.getBrowseTab();
                    $(".data_container .column_label", namespace).each(function() {
                        o_browse.createTooltip(this, $(this).text() );
                     }); // end each
                     $(".data_table", namespace).stickyTableHeaders({ fixedOffset: 125 });

                }
        });

    },

    infiniteScrollPageIndicatorRow: function(page) {
        opus.prefs.view == 'browse' ? browse_prefix = '' : browse_prefix = 'colls_';

        id = 'inifite_scroll_' + browse_prefix + opus.prefs.browse + '__' + page;

        data = '<tr class = "inifite_scroll_page"> \
                <td><span class = "back_to_top"><a href = "#top">top</a></span></td> \
                <td colspan = "' + opus.prefs['cols'].length + '">\
                <span class = "infinite_scroll_page_container" id = "' + id + '">Page ' + page + '</span><span class = "infinite_scroll_spinner">' + opus.spinner + '</span> \
                </td></tr>';

        gallery = '<li class = "inifite_scroll_page">\
                   <span class = "back_to_top"><a href = "#top">back to top</a></span>\
                   <span class = "infinite_scroll_page_container" id = "' + id + '">Page ' + page + '</span><span class = "infinite_scroll_spinner">' + opus.spinner + '</span></li>';

        // opus.page_bar_offsets['#'+id] = false; // we look up the page loc later - to be continued

        if (opus.prefs.browse == 'gallery') {
            return gallery; }
        return data;
    },

    // there are interactions that are applied to different code snippets,
    // this returns the namespace, view_var, prefix, and add_to_url
    // that distinguishes collections vs result tab views
    // usage:
    /*
        view_info = o_browse.getViewInfo();
        namespace = view_info['namespace'];
        view_var = view_info['view_var'];
        prefix = view_info['prefix'];
        add_to_url = view_info['add_to_url'];
    */
    getViewInfo: function() {
        // this function handles fetching the browse views - gallery or table - for both the Browse and Collections tabs
        if (opus.prefs.view == 'collections') {
            namespace = '#collections';
            view_var = 'colls_browse';  // which view is showing on page, gallery or table, contained in opus.prefs.[view_var]
            prefix = 'colls_';
            add_to_url = "&colls=true";
        } else {
            namespace = '#browse';
            view_var = 'browse';
            prefix = '';
            add_to_url = "";
        }
        return {'namespace':namespace, 'view_var':view_var, 'prefix':prefix, 'add_to_url':add_to_url}

    },

    getBrowseTab: function() {

        view_info = o_browse.getViewInfo();
        namespace = view_info['namespace'];
        view_var = view_info['view_var'];
        prefix = view_info['prefix'];
        add_to_url = view_info['add_to_url'];

        opus.browse_empty = false;

        clearInterval(opus.scroll_watch_interval); // hold on cowboy only 1 page at a time

        o_browse.browseControlIndicator(false);

        var url = "/opus/api/images/small.html?alt_size=full&"

        if (opus.prefs[prefix + 'browse'] == 'data') {

            if (!$('.data_table', namespace).length) {
                o_browse.startDataTable(namespace);
                return; // startDataTable() starts data table and then calls getBrowseTab again
            }
            url = '/api/data.html?'
        }


        url += o_hash.getHash() + '&reqno=' + opus.lastRequestNo + add_to_url;

        $('#' + prefix + 'page_no', namespace).val(opus.prefs[prefix + 'page']);
        $('#' + prefix + 'pages', namespace).html(opus[prefix + 'pages']);

        // $(".browse_footer_label", '#browse').empty().html(opus.spinner);   made default


        opus.prefs[view_var] == 'gallery' ? footer_clicks = opus.browse_footer_clicks[prefix + 'gallery'] : footer_clicks = opus.browse_footer_clicks[prefix + 'data'];

        // figure out the page

        start_page = opus.prefs[prefix + 'page'];
        needs_indicator_bar = false;
        if (opus.browse_footer_clicked) {
            opus.browse_footer_clicked=false;
            needs_indicator_bar = true;
            page = parseInt(start_page) + parseInt(footer_clicks);
        } else {
            page = start_page;
        }

        if (opus[prefix + 'pages'] && page > opus[prefix + 'pages']) {
            // the page is higher than the total number of pages, reset it to the last page
            page = opus[prefix + 'pages'];
            $('#' + prefix + 'page_no', namespace).val(page); // reset the display
        }

        // did we already fetch this page?
        last_page = opus.last_page[view_var][opus.prefs.browse];
        if (page == last_page && !opus.browse_tab_click) {
            // we already fetched this page, do nothing
            return;
        }
        opus.browse_tab_click = false;

        if (page < 1) {
            page = 1;
            $('#' + prefix + 'page_no', namespace).val(page); // reset the display
        }

        if (needs_indicator_bar) {
            indicator_row = o_browse.infiniteScrollPageIndicatorRow(page);
            opus.prefs[view_var] == 'gallery' ? $(indicator_row).appendTo('.gallery', namespace).show() : $(indicator_row).appendTo(".data_table", namespace).show();
            $('.infinite_scroll_spinner', namespace).show();
        }
        url += '&page=' + page;


        // NOTE if you change alt_size=full here you must also change it in gallery.html template
        $.ajax({ url: url,
            success: function(html){
               // bring in the new images
               function appendBrowsePage() {
                   // append browse page

                    /**
                    if (footer_clicks) {
                        // user is infinite scrolling, append a row that indicates page number here
                        // opus.prefs.browse == 'gallery' ? $(html).appendTo('.gallery', '#browse') : $(html).appendTo(".data_table",'#browse');
                    }
                    **/

                    // alert(html);
                    opus.prefs[view_var] == 'gallery' ? $('.gallery', namespace).append(html) : $(".data_table", namespace).append(html);

                    opus.last_page[view_var][opus.prefs.browse] = page;

                    $('.infinite_scroll_spinner', namespace).fadeOut("fast");

                    // turn the scroll watch timer back on
                    opus.scroll_watch_interval = setInterval(o_browse.browseScrollWatch, 1000);

                    // ignite the shadowbox
                    Shadowbox.setup(".gallery .shadowbox", namespace);

                    // bring back the nav bar and footer button
                    $('.nav', namespace).css('visibility','visible');
                    /* this is now default no showing/hiding
                        $('.browse_footer_label', '#browse').html('<a href = "">more</a>');
                    */
                    opus.prefs[view_var] == 'gallery' ? footer_clicks = opus.browse_footer_clicks[prefix + 'gallery'] : footer_clicks = opus.browse_footer_clicks[prefix + 'data'];

                    // if they've clicked here x times show the checkbox
                    if (parseInt(footer_clicks) > opus.footer_clicks_trigger) {
                        $('.browse_footer_checkbox', namespace).html('<input type="checkbox" name="browse_auto" ' + opus.browse_auto + '>load automatically when scrolling to end');
                    }
               }
               appendBrowsePage();

               /* we are removing this footer, scrolling is always auto
               // if user is in auto mode remove the classes from the footer that make it appear clickable
               if (opus.browse_auto == 'checked' && !opus.browse_footer_style_disabled) {
                   // $(',browse_footer', '#browse').css('cursor','auto');
                   $('.browse_footer', '#browse').removeClass('button');
                   $('.browse_footer', '#browse').addClass('button_disabled');
                   opus.browse_footer_style_disabled = true;
               } else if (opus.browse_auto != 'checked' && opus.browse_footer_style_disabled) {
                   $('.browse_footer', '#browse').removeClass('button_disabled');
                   $('.browse_footer', '#browse').addClass('button');
                   opus.browse_footer_style_disabled = false;
               }
               */

            }
        });
    },


    // we watch the paging inputs to wait for pauses before we trigger page change. UX, baby.
    textInputMonitor: function(field,ms) {

        // which field are we working on? defines which global monitor list we use
    	switch(field) {
    		case 'page':
    			field_monitor = opus.page_monitor;
    			prefix = '';
    			break;
    		case 'colls_page':
    			field_monitor = opus.page_colls_monitor;
    			prefix = 'colls_';
    			break;
    		default:
    		    var field_monitor = opus.text_field_monitor;
    	}
    	var value = parseInt($('#' + prefix + 'page_no').val());

        if (opus.input_timer) clearTimeout(opus.input_timer);

		opus.input_timer = setTimeout(
		    function() {
                if (field_monitor[field_monitor.length-1]  == value){
					// the user has not moved in 2 seconds
					o_browse.updatePage(parseInt(value));
					// opus.force_load = true;
					// setTimeout("o_hash.updateHash()",0);
					// tidy up, keep the array small..
					if (field_monitor.length > 3) field_monitor.shift();
				} else {
					// array is changing, user is still typing
					// maintain our array with our new value
                    field_monitor[field_monitor.length]  = value;
					o_browse.textInputMonitor(field,ms);
				}
		    },ms);

        	// update the global monitor
        	switch(field) {
        		case 'page':
        				opus.page_monitor = field_monitor;
        				break;
        		case 'page_colls':
        				opus.page_colls_monitor = field_monitor;
        				break;
        		default:
        				opus.text_field_monitor = field_monitor;
        	}
        },

        updatePage: function(page) {
            opus.browse_footer_clicks = {'gallery':0, 'data':0}
			opus.prefs.page = page;
			o_hash.updateHash();
			$('.gallery', '#browse').empty();
			$(".data_container", '#browse').empty();
            o_browse.getBrowseTab();

        },

        // http://stackoverflow.com/questions/487073/jquery-check-if-element-is-visible-after-scroling thanks!
        isScrolledIntoView: function(elem) {

                var docViewTop = $(window).scrollTop();
                var docViewBottom = docViewTop + $(window).height();

                var elemTop = $(elem).offset().top;
                var elemBottom = elemTop + $(elem).height();

                return ((elemBottom >= docViewTop) && (elemTop <= docViewBottom)
                  && (elemBottom <= docViewBottom) &&  (elemTop >= docViewTop) );
        },


        // this is on a setInterval
        browseScrollWatch: function() {
            // this is for the infinite scroll footer bar
            if (opus.browse_auto && o_browse.isScrolledIntoView('#end_of_page')) {

                if (opus.prefs.view=='browse') {
                    opus.prefs.browse == 'gallery' ? opus.browse_footer_clicks['gallery']++ : opus.browse_footer_clicks['data']++;
                } else if (opus.prefs.view=='collections'){
                    opus.prefs.colls_browse == 'gallery' ? opus.browse_footer_clicks['colls_gallery']++ : opus.browse_footer_clicks['colls_data']++;
                }
                opus.browse_footer_clicked=true;
                o_browse.getBrowseTab();
            }
        },

        GalleryFooterClick: function() {
           delay = 0;  // a pause before the next set of gallery images is drawn

           opus.browse_footer_clicked=true;
           // they clicked the footer bar, did they check the box?
           if ($('input[name=browse_auto]').is(':checked')) {   // box is checked
               if (opus.browse_auto != 'checked') {
                    // box was unchecked before and now it is checked,
                    // aka they are checking the box for the first time,
                    // slight pause to let them see their check get drawn
                   delay = 500;
                   opus.browse_auto = 'checked'
               }
           } else { // auto box is unchecked
               opus.browse_auto = '';
               opus.prefs.browse == 'gallery' ? opus.browse_footer_clicks['gallery']++ : opus.browse_footer_clicks['data']++;
               setTimeout('o_browse.getBrowseTab()',delay)
           }

           return false;
        },

        getColumnChooser: function() {
            /**
            offset = $('.data_table', '#browse').offset().top + $('.data_table .column_label', '#browse').height() + 10;
            left = $('.get_column_chooser').parent().offset().left - $('#column_chooser').width()  ;
            $('#column_chooser').css('top', Math.floor(offset) + 'px');
            $('#column_chooser').css('left', Math.floor(left) + 'px');
            **/

            if (opus.column_chooser_drawn) {
                if ($('#column_chooser').is(":visible")) {
                    $('#column_chooser').effect("highlight", {}, 3000);
                } else {
                    $('#column_chooser').jqmShow();
                }
                return;
            }

            // column_chooser has not been drawn, fetch it from the server and apply its behaviors:
            $('#column_chooser').html(opus.spinner);
            $('#column_chooser').jqm({
                overlay: 0,
            })

            $('#column_chooser').jqmShow();

            url = '/forms/column_chooser.html?' + o_hash.getHash();
            $('#column_chooser').load( url, function(response, status, xhr)  {
                       opus.column_chooser_drawn=true;

                       // we keep these all open in the column chooser, they are all closed by default
                       $('.menu_cat_triangle','#browse').toggleClass('opened_triangle');
                       $('.menu_cat_triangle','#browse').toggleClass('closed_triangle');

                       o_browse.addColumnChooserBehaviors();
                       $('#column_chooser','#browse').draggable();
                       $('#column_chooser','#browse').resizable();

                       // dragging to reorder the chosen
                       $( ".chosen_columns>ul").sortable({
                           cursor: 'crosshair',
                           stop: function(event, ui) { o_browse.columnsDragged(this); }
                       });

            });



        },

        columnsDragged: function(element) {
            var cols = $(element).sortable('toArray')
            $.each(cols, function(key, value)  {
                cols[key] = value.split('__')[1];
            })
            opus.prefs['cols'] = cols
            o_hash.updateHash();
            // if we are in gallery - just change the data-struct that gallery draws from
            // if we are in table -
            // $('.gallery', '#browse').html(opus.spinner);
            o_browse.updateBrowse();
        },


        // this is used to update the browse tab after a column change
        updateBrowse: function() {
            opus.browse_footer_clicks = 0;
            $('.data_table','#browse').remove();
            o_browse.getBrowseTab();
        },




};