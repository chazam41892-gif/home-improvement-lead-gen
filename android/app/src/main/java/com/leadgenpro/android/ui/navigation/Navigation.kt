package com.leadgenpro.android.ui.navigation

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.leadgenpro.android.ui.screens.*

sealed class Screen(val route: String, val title: String, val icon: ImageVector, val selectedIcon: ImageVector) {
    data object Dashboard : Screen("dashboard", "Dashboard", Icons.Outlined.Dashboard, Icons.Filled.Dashboard)
    data object Search : Screen("search", "Search", Icons.Outlined.Search, Icons.Filled.Search)
    data object Leads : Screen("leads", "Leads", Icons.Outlined.People, Icons.Filled.People)
    data object LandingPages : Screen("landing_pages", "Landing Pages", Icons.Outlined.Web, Icons.Filled.Web)
    data object Schedules : Screen("schedules", "Schedules", Icons.Outlined.Schedule, Icons.Filled.Schedule)
    data object Nurture : Screen("nurture", "Nurture", Icons.Outlined.Favorite, Icons.Filled.Favorite)
    data object Ads : Screen("ads", "Ads", Icons.Outlined.Campaign, Icons.Filled.Campaign)
    data object Settings : Screen("settings", "Settings", Icons.Outlined.Settings, Icons.Filled.Settings)
    data object LeadDetail : Screen("lead_detail/{leadId}", "Lead Detail", Icons.Outlined.Person, Icons.Filled.Person) {
        fun createRoute(leadId: String) = "lead_detail/$leadId"
    }
    data object Appointments : Screen("appointments", "Appointments", Icons.Outlined.Event, Icons.Filled.Event)
    data object TradeDiscovery : Screen("trade_discovery", "Discover", Icons.Outlined.Explore, Icons.Filled.Explore)
    data object Revenue : Screen("revenue", "Revenue", Icons.Outlined.TrendingUp, Icons.Filled.TrendingUp)
    data object TradeConvert : Screen("trade_convert/{businessName}/{phone}/{email}", "Convert", Icons.Outlined.SwapHoriz, Icons.Filled.SwapHoriz) {
        fun createRoute(businessName: String, phone: String, email: String) =
            "trade_convert/$businessName/$phone/$email"
    }
}

val bottomNavItems = listOf(
    Screen.Dashboard,
    Screen.Search,
    Screen.Leads,
    Screen.LandingPages,
)

val moreNavItems = listOf(
    Screen.Schedules,
    Screen.Nurture,
    Screen.Ads,
    Screen.TradeDiscovery,
    Screen.Revenue,
    Screen.Settings,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppNavigation() {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    val showBottomBar = currentRoute in bottomNavItems.map { it.route } ||
            currentRoute in moreNavItems.map { it.route } ||
            currentRoute == Screen.LeadDetail.route ||
            currentRoute == Screen.TradeConvert.route

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                AppBottomBar(navController = navController, currentRoute = currentRoute)
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Dashboard.route,
            modifier = Modifier.padding(innerPadding)
        ) {
            composable(Screen.Dashboard.route) {
                DashboardScreen(navController = navController)
            }
            composable(Screen.Search.route) {
                SearchScreen(navController = navController)
            }
            composable(Screen.Leads.route) {
                LeadsScreen(navController = navController)
            }
            composable(Screen.LandingPages.route) {
                LandingPagesScreen()
            }
            composable(Screen.Schedules.route) {
                SchedulesScreen()
            }
            composable(Screen.Nurture.route) {
                NurtureScreen()
            }
            composable(Screen.Ads.route) {
                AdsScreen()
            }
            composable(Screen.Settings.route) {
                SettingsScreen()
            }
            composable(Screen.TradeDiscovery.route) {
                TradeDiscoveryScreen(navController = navController)
            }
            composable(Screen.Revenue.route) {
                RevenueScreen(navController = navController)
            }
            composable(
                route = Screen.TradeConvert.route,
                arguments = listOf(
                    navArgument("businessName") { type = NavType.StringType },
                    navArgument("phone") { type = NavType.StringType },
                    navArgument("email") { type = NavType.StringType }
                )
            ) { backStackEntry ->
                val businessName = backStackEntry.arguments?.getString("businessName") ?: ""
                val phone = backStackEntry.arguments?.getString("phone") ?: ""
                val email = backStackEntry.arguments?.getString("email") ?: ""
                TradeConvertScreen(
                    navController = navController,
                    businessName = businessName,
                    phone = phone,
                    email = email
                )
            }
            composable(
                route = Screen.LeadDetail.route,
                arguments = listOf(navArgument("leadId") { type = NavType.StringType })
            ) { backStackEntry ->
                val leadId = backStackEntry.arguments?.getString("leadId") ?: ""
                LeadDetailScreen(leadId = leadId, navController = navController)
            }
            composable(Screen.Appointments.route) {
                NurtureScreen()
            }
        }
    }
}

@Composable
fun AppBottomBar(navController: NavHostController, currentRoute: String?) {
    var showMoreMenu by remember { mutableStateOf(false) }

    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface
    ) {
        bottomNavItems.forEach { screen ->
            NavigationBarItem(
                icon = {
                    Icon(
                        imageVector = if (currentRoute == screen.route) screen.selectedIcon else screen.icon,
                        contentDescription = screen.title
                    )
                },
                label = { Text(screen.title, style = MaterialTheme.typography.labelSmall) },
                selected = currentRoute == screen.route,
                onClick = {
                    if (currentRoute != screen.route) {
                        navController.navigate(screen.route) {
                            popUpTo(navController.graph.startDestinationId) { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer
                )
            )
        }

        Box {
            NavigationBarItem(
                icon = {
                    Icon(
                        imageVector = if (showMoreMenu) Icons.Filled.MoreHoriz else Icons.Outlined.MoreHoriz,
                        contentDescription = "More"
                    )
                },
                label = { Text("More", style = MaterialTheme.typography.labelSmall) },
                selected = showMoreMenu,
                onClick = { showMoreMenu = true },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer
                )
            )

            DropdownMenu(
                expanded = showMoreMenu,
                onDismissRequest = { showMoreMenu = false },
                modifier = Modifier.offset(y = (-200).dp)
            ) {
                moreNavItems.forEach { screen ->
                    DropdownMenuItem(
                        text = { Text(screen.title) },
                        onClick = {
                            showMoreMenu = false
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        leadingIcon = {
                            Icon(
                                imageVector = if (currentRoute == screen.route) screen.selectedIcon else screen.icon,
                                contentDescription = screen.title
                            )
                        }
                    )
                }
            }
        }
    }
}
